from __future__ import annotations

from ntpath import basename
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Tuple

import numpy as np
from attrs import define

from .. import config
from ..enums import BuildTarget, ClassIDType
from ..helpers.ContainerHelper import ContainerHelper
from ..helpers.Tpk import get_common_strings
from ..helpers.TypeTreeHelper import TypeTreeNode
from ..helpers.UnityVersion import UnityVersion
from ..streams import EndianBinaryWriter
from . import BundleFile, File
from .ObjectReader import ObjectReader

if TYPE_CHECKING:
    from ..classes import AssetBundle, Object
    from ..files import ObjectReader
    from ..streams.EndianBinaryReader import EndianBinaryReader


# Packed record for one object EXCLUDED by type_filter — deliberately a NumPy
# structured dtype (unboxed, ~32 bytes/record), not a Python tuple/namedtuple
# (~150-250 bytes/record once you count the object header plus 5-7 separately
# boxed ints) or a full ObjectReader (~300+ bytes, plus it's exactly the thing
# type_filter exists to avoid constructing). At the scale type_filter is meant
# for — tens of millions of objects, most of them excluded — that difference
# is the entire point: a Python-object-per-excluded-record design would give
# back most of the RAM type_filter was supposed to save, just to make saving
# possible. See save()'s own comment for how this array gets used to write a
# type-filtered load back out losslessly for whatever wasn't touched, instead
# of refusing to save at all (the previous, and still the fallback, behavior
# — see _partial_load below).
#
# is_destroyed/is_stripped are 0 when this format version doesn't declare
# them at all — never actually read back in that case either, since save()'s
# write-back for these two fields is gated by the exact same header.version
# checks used when reading them (see ObjectReader.from_reader_filtered()'s
# own comment).
_EXCLUDED_OBJECT_DTYPE = np.dtype([
    ("path_id", "i8"),
    ("type_id", "i4"),
    ("class_id", "i4"),
    ("is_destroyed", "i2"),
    ("is_stripped", "i2"),
    ("byte_start", "i8"),
    ("byte_size", "u4"),
])


@define(slots=True)
class SerializedFileHeader:
    metadata_size: int
    file_size: int
    version: int
    data_offset: int
    endian: str
    reserved: bytes

    def __init__(self, reader: EndianBinaryReader):
        (
            self.metadata_size,
            self.file_size,
            self.version,
            self.data_offset,
        ) = reader.read_u_int_array(4)


@define(slots=True)
class LocalSerializedObjectIdentifier:  # script type
    local_serialized_file_index: int
    local_identifier_in_file: int

    def __init__(self, header: SerializedFileHeader, reader: EndianBinaryReader):
        self.local_serialized_file_index = reader.read_int()
        if header.version < 14:
            self.local_identifier_in_file = reader.read_int()
        else:
            reader.align_stream()
            self.local_identifier_in_file = reader.read_long()

    def write(self, header: SerializedFileHeader, writer: EndianBinaryWriter):
        writer.write_int(self.local_serialized_file_index)
        if header.version < 14:
            writer.write_int(self.local_identifier_in_file)
        else:
            writer.align_stream()
            writer.write_long(self.local_identifier_in_file)


@define(slots=True)
class FileIdentifier:  # external
    path: str
    temp_empty: Optional[str] = None
    guid: Optional[bytes] = None
    type: Optional[int] = None
    # enum { kNonAssetType = 0, kDeprecatedCachedAssetType = 1, kSerializedAssetType = 2, kMetaAssetType = 3 };

    @property
    def name(self):
        return basename(self.path)

    def __repr__(self):
        return f"<{self.__class__.__name__}({self.path})>"

    def __init__(self, header: SerializedFileHeader, reader: EndianBinaryReader):
        if header.version >= 6:
            self.temp_empty = reader.read_string_to_null()
        if header.version >= 5:
            self.guid = reader.read_bytes(16)
            self.type = reader.read_int()
        self.path = reader.read_string_to_null()

    def write(self, header: SerializedFileHeader, writer: EndianBinaryWriter):
        if header.version >= 6:
            assert self.temp_empty is not None
            writer.write_string_to_null(self.temp_empty)
        if header.version >= 5:
            assert self.guid is not None and self.type is not None
            writer.write_bytes(self.guid)
            writer.write_int(self.type)
        writer.write_string_to_null(self.path)


@define(slots=True, init=False)
class SerializedType:
    class_id: int
    is_stripped_type: Optional[bool] = None
    script_type_index: int = -1
    script_id: Optional[bytes] = None  # Hash128
    old_type_hash: Optional[bytes] = None  # Hash128
    node: Optional[TypeTreeNode] = None
    # 23+: hash identifying the type tree when it is stored outside this file ("extracted"
    # type trees); kept so a file can be written back unchanged. `node` is None for such a
    # type — the tree is not in this file — exactly like a file with type trees stripped.
    ext_type_hash: Optional[bytes] = None  # Hash128
    # ref type
    m_ClassName: Optional[str] = None
    m_NameSpace: Optional[str] = None
    m_AssemblyName: Optional[str] = None
    # 21+
    type_dependencies: Optional[Tuple[int, ...]] = None

    def __init__(
        self,
        reader: EndianBinaryReader,
        serialized_file: SerializedFile,
        is_ref_type: bool,
    ):
        version = serialized_file.header.version
        self.class_id = reader.read_int()
        self.__attrs_init__(self.class_id)

        if version >= 16:
            self.is_stripped_type = reader.read_boolean()

        if version >= 17:
            self.script_type_index = reader.read_short()

        if version >= 13:
            if (
                (is_ref_type and self.script_type_index >= 0)
                or (version < 16 and self.class_id < 0)
                or (version >= 16 and self.class_id == 114)
            ):
                self.script_id = reader.read_bytes(16)
            self.old_type_hash = reader.read_bytes(16)

        if serialized_file._enable_type_tree:
            if version >= 23:
                # Layout (AssetsTools.NET TypeTreeType.Read, the reference for this):
                #   Hash128 ext_type_hash, int32 tree_size, then — only if tree_size != 0 —
                #   the tree blob, `mhtt` header included (see TypeTreeNode.parse_blob).
                # tree_size == 0 means the tree lives outside this file and NO blob follows.
                # (An inline blob is thus 16 + 4 + 8 = 28 bytes before its node count, which is
                # why a plain "skip 28 bytes" appears to work — until a type has no blob.)
                self.ext_type_hash = reader.read_bytes(16)
                tree_size = reader.read_int()
                if tree_size < 0:
                    raise ValueError(f"Negative type tree size ({tree_size}) in type {self.class_id}")
                if tree_size:
                    blob_start = reader.Position
                    self.node = TypeTreeNode.parse_blob(reader, version)
                    consumed = reader.Position - blob_start
                    if consumed != tree_size:
                        raise ValueError(
                            f"Type tree of type {self.class_id} declares {tree_size} bytes, "
                            f"but its blob is {consumed} bytes long"
                        )
            elif version >= 12 or version == 10:
                self.node = TypeTreeNode.parse_blob(reader, version)
            else:
                self.node = TypeTreeNode.parse(reader, version)

            if version >= 21:
                if is_ref_type:
                    self.m_ClassName = reader.read_string_to_null()
                    self.m_NameSpace = reader.read_string_to_null()
                    self.m_AssemblyName = reader.read_string_to_null()
                else:
                    self.type_dependencies = reader.read_int_array()

    def write(
        self,
        serialized_file: SerializedFile,
        writer: EndianBinaryWriter,
        is_ref_type: bool,
    ):
        version = serialized_file.header.version
        writer.write_int(self.class_id)

        if version >= 16:
            assert self.is_stripped_type is not None
            writer.write_boolean(self.is_stripped_type)

        if version >= 17:
            assert self.script_type_index is not None
            writer.write_short(self.script_type_index)

        if version >= 13:
            if (
                (is_ref_type and self.script_type_index >= 0)
                or (version < 16 and self.class_id < 0)
                or (version >= 16 and self.class_id == 114)
            ):
                assert self.script_id is not None
                writer.write_bytes(self.script_id)  # Hash128
            assert self.old_type_hash is not None
            writer.write_bytes(self.old_type_hash)  # Hash128

        if serialized_file._enable_type_tree:
            if version >= 23:
                writer.write_bytes(self.ext_type_hash or bytes(16))  # Hash128
                if self.node is None:
                    writer.write_int(0)  # external type tree: no blob follows
                else:
                    # The size field counts the whole blob (header included), so it is written
                    # after serializing it.
                    blob_writer = EndianBinaryWriter(endian=writer.endian)
                    self.node.dump_blob(blob_writer, version)
                    blob = blob_writer.bytes
                    writer.write_int(len(blob))
                    writer.write_bytes(blob)
            else:
                assert self.node is not None
                if version >= 12 or version == 10:
                    self.node.dump_blob(writer, version)
                else:
                    serialized_file.dump(writer, version)

            if version >= 21:
                if is_ref_type:
                    assert (
                        self.m_ClassName is not None
                        and self.m_NameSpace is not None
                        and self.m_AssemblyName is not None
                    )
                    writer.write_string_to_null(self.m_ClassName)
                    writer.write_string_to_null(self.m_NameSpace)
                    writer.write_string_to_null(self.m_AssemblyName)
                else:
                    assert self.type_dependencies is not None
                    writer.write_int_array(self.type_dependencies, True)

    @property
    def nodes(self) -> Optional[TypeTreeNode]:
        # for compatibility with old versions
        return self.node


def _find_serialized_type_by_id(types: list, type_id: int, version: int):
    """Same lookup ObjectReader.from_reader()/from_reader_filtered() use at
    read time to resolve a SerializedType (types[type_id] directly for
    version>=16, a linear scan matching typ.class_id==type_id below that) —
    replicated here so a passthrough (type_filter-excluded) object's
    script_type_index can be found the same way at save time, since a
    passthrough record has no serialized_type reference of its own."""
    if version < 16:
        for typ in types:
            if typ.class_id == type_id:
                return typ
        return None
    if 0 <= type_id < len(types):
        return types[type_id]
    return None


def _write_passthrough_object(record, assets_file: "SerializedFile", header, writer, data_writer):
    """Writes one type_filter-EXCLUDED object's table entry + raw data,
    sourced byte-for-byte from the original file instead of from a live
    ObjectReader — there isn't one, that's the whole point (see
    _EXCLUDED_OBJECT_DTYPE's own comment). Field-for-field mirror of
    ObjectReader.write(); only the DATA source differs (a fresh read from
    the original reader at the object's own original byte range, instead of
    self.data/self.reader on a live instance)."""
    path_id = int(record["path_id"])
    type_id = int(record["type_id"])
    class_id = int(record["class_id"])
    byte_start = int(record["byte_start"])
    byte_size = int(record["byte_size"])

    if assets_file.big_id_enabled:
        writer.write_long(path_id)
    elif header.version < 14:
        writer.write_int(path_id)
    else:
        writer.align_stream()
        writer.write_long(path_id)

    reader = assets_file.reader
    with reader.lock:
        reader.Position = byte_start
        data = reader.read(byte_size)

    if header.version >= 22:
        writer.write_long(data_writer.Position)
    else:
        writer.write_u_int(data_writer.Position)

    writer.write_u_int(len(data))
    data_writer.write(data)

    writer.write_int(type_id)

    if header.version < 16:
        writer.write_u_short(class_id)

    if header.version < 11:
        writer.write_u_short(int(record["is_destroyed"]))

    if 11 <= header.version < 17:
        serialized_type = _find_serialized_type_by_id(assets_file.types, type_id, header.version)
        script_type_index = serialized_type.script_type_index if serialized_type is not None else 0
        writer.write_short(script_type_index)

    if header.version == 15 or header.version == 16:
        writer.write_byte(int(record["is_stripped"]))


class SerializedFile(File.File):
    reader: EndianBinaryReader
    version: UnityVersion
    unity_version: str
    target_platform: BuildTarget
    _enable_type_tree: bool
    types: List[SerializedType]
    script_types: List[LocalSerializedObjectIdentifier]
    externals: List[FileIdentifier]
    ref_types: Optional[List[SerializedType]]
    objects: Dict[int, ObjectReader]
    unknown: int
    header: SerializedFileHeader
    _m_target_platform: int
    big_id_enabled: int
    userInformation: Optional[str]
    assetbundle: Optional[AssetBundle]
    _cache: Dict[str, Object]

    @property
    def files(self):
        if self.objects:
            return self.objects
        return {}

    @files.setter
    def files(self, value):
        self.objects = value

    @property
    def bytes(self) -> bytes:
        """Raw, untouched bytes for this entry. Only meaningful for a SerializedFile
        parsed in object_count_only mode that was never subsequently re-parsed in
        full (self._object_count_only_stub) — accessing this on a normally-parsed
        file raises AttributeError on purpose, so the existing, unrelated
        `f.bytes if hasattr(f, "bytes") else f.save()` dispatch already used by
        BundleFile.save_fs()/save_fs_to_file() for untouched entries (see
        FlaggedBytesSource) picks this up for free and keeps calling f.save() for
        every other SerializedFile exactly as before.

        Real bug this fixes: a stub's own object table was SKIPPED during parsing
        (object_count_only mode seeks past it without reading it — see __init__),
        not read-as-empty, so self.objects is {} for a reason that has nothing to
        do with the real file's actual contents. Calling .save() on a stub would
        either crash (`ref_types`/`userInformation` were never assigned at all,
        surfacing as a bare `AttributeError: 'SerializedFile' object has no
        attribute 'ref_types'` the moment save() reads them) or, had those two
        merely been defaulted to None/[] instead, silently write out a corrupted
        0-object replacement of a real file. This surfaced via the CAB browser:
        opening a bundle there only fully parses the ONE internal file the user
        picks (plus its declared dependencies) — every other entry stays an
        object_count_only stub — and rebuilding the whole archive afterward
        (Save Game Files) used to crash on the first untouched entry it reached."""
        if not self._object_count_only_stub:
            raise AttributeError("bytes")
        reader = self.reader
        pos = reader.Position
        try:
            reader.Position = 0
            return bytes(reader.read_bytes(reader.Length))
        finally:
            reader.Position = pos

    def __init__(self, reader: EndianBinaryReader, parent=None, name=None, type_filter=None, object_count_only=False, **kwargs):
        super().__init__(parent=parent, name=name, **kwargs)
        self.reader = reader

        self.unity_version = "2.5.0f5"
        self.target_platform = BuildTarget.UnknownPlatform
        self._enable_type_tree = True
        self.types = []
        self.script_types = []
        self.externals = []
        self.objects = {}
        # populated only in object_count_only mode (see below)
        self.object_count = 0
        self.class_ids = set()
        # used to speed up mass asset extraction
        # some assets refer to each other, so by keeping the result
        # of specific assets cached the extraction can be speed up by a lot.
        # used by: Sprite (Texture2D (with alpha) cached),
        self._cache = {}
        self.unknown = 0
        self._partial_load = type_filter is not None # NEW
        # Populated only in the type_filter real-load branch below — a
        # compact NumPy array of every object type_filter excluded, kept
        # specifically so save() can still write this file back out
        # losslessly (see _EXCLUDED_OBJECT_DTYPE's own comment and save()'s).
        # None here means either type_filter wasn't used, or (object_count_only
        # mode) the object table was never read at all.
        self._excluded_objects: Optional[np.ndarray] = None
        # Set True only by the object_count_only early-return branch below. A
        # SerializedFile parsed that way never read its object table (self.objects
        # stays {}) and never reads ref_types/userInformation at all — save()'s own
        # `assert self.ref_types is not None` doesn't even get that far, since the
        # attribute was never assigned (bare AttributeError). See the `bytes`
        # property below for why this flag exists: it's how save_fs()/
        # save_fs_to_file() tell a genuinely-unparsed stub apart from a real,
        # fully-read SerializedFile that happens to have 0 objects.
        self._object_count_only_stub = False

        # ReadHeader
        header = SerializedFileHeader(reader)
        self.header = header

        if header.version >= 9:
            header.endian = ">" if reader.read_boolean() else "<"
            header.reserved = reader.read_bytes(3)
            if header.version >= 22:
                header.metadata_size = reader.read_u_int()
                header.file_size = reader.read_long()
                header.data_offset = reader.read_long()
                self.unknown = reader.read_long()  # unknown
        else:
            reader.Position = header.file_size - header.metadata_size
            header.endian = ">" if reader.read_boolean() else "<"

        reader.endian = header.endian

        # The metadata (types, object table, scripts, externals, ...) is parsed from ONE in-memory copy when the
        # file sits in a bundle: through the bundle's locked block reader the type list alone was ~290 k tiny
        # reads for Lego Party. The copy starts at file offset 0, so every position — and every align_stream(),
        # which aligns to the ABSOLUTE offset — is what it was. `data_reader` stays the real reader: the
        # ObjectReaders read their data through it (and self.reader is it).
        data_reader = reader
        meta_in_memory = False
        if header.version >= 9 and header.metadata_size > 0:
            from ..streams.EndianBinaryReader import EndianBinaryReader, EndianBinaryReader_Streamable

            if isinstance(reader, EndianBinaryReader_Streamable):
                meta_end = min(reader.Position + header.metadata_size, reader.Length)
                header_end = reader.Position
                reader.Position = 0
                meta = bytes(reader.read_bytes(meta_end))
                reader.Position = header_end
                reader = EndianBinaryReader(meta, endian=header.endian)
                reader.Position = header_end
                meta_in_memory = True

        if header.version >= 7:
            unity_version = reader.read_string_to_null()
            self.set_version(unity_version)

        if header.version >= 8:
            self._m_target_platform = reader.read_int()
            self.target_platform = BuildTarget(self._m_target_platform)

        if header.version >= 13:
            self._enable_type_tree = reader.read_boolean()

        # ReadTypes
        type_count = reader.read_int()
        self.types = [SerializedType(reader, self, False) for _ in range(type_count)]

        self.big_id_enabled = 0
        if 7 <= header.version < 14:
            self.big_id_enabled = reader.read_int()

        # ReadObjects
        object_count = reader.read_int()
        self.objects = {}

        if object_count_only:
            # Cheapest mode: only the object count and the set of types.
            # We don't read or decompress the object table itself — skip past it via seek
            # (seek on a streamable reader does NOT trigger decompression, see CLAUDE.md).
            from ..helpers.bundle_inspector import _object_record_size

            self.object_count = object_count
            self.class_ids = {t.class_id for t in self.types}
            self.assetbundle = None
            self._container = ContainerHelper([])

            if object_count > 0:
                raw_size, needs_align = _object_record_size(header.version, bool(self.big_id_enabled))
                if needs_align:
                    reader.align_stream()
                pad = (-raw_size) % 4 if needs_align else 0
                record_size = raw_size + pad
                reader.Position += object_count * record_size
            self._object_count_only_stub = True
            return

        # Split into two loops rather than one checking `type_filter is None
        # or obj.class_id in type_filter` per-iteration — the unfiltered
        # branch (by far the common case) stays an exact, untouched copy of
        # the original single-loop behavior; the filtered branch uses
        # from_reader_filtered(), which skips constructing an ObjectReader
        # entirely for an excluded object instead of building one and then
        # discarding it (see that method's own docstring for why this is
        # the fix for "Filtered mode doesn't actually load faster").
        # Bulk table read: objects of a file inside a bundle live behind a lazy, locked block reader, where
        # each of the ~4 tiny reads per record costs microseconds of Python (block lookup, lock, seek) — for
        # a Lego Party-sized install (4.4M objects) that was ~70 % of the whole load. Fixed-size records are
        # read in batches into memory instead and parsed from there (the ObjectReader keeps the real reader).
        # A batch (fixed-size records copied into memory) is decoded in one numpy step (_read_object_batch);
        # chunk None = the per-record path, record by record from `reader`.
        batches = self._object_table_batches(reader, header, object_count, in_memory=meta_in_memory)
        table_reader = reader if meta_in_memory else None      # where the per-record path reads the fields

        if type_filter is None:
            for count, chunk in batches:
                if chunk is not None:
                    self._read_object_batch(data_reader, chunk, count, None)
                    continue
                for _ in range(count):
                    obj = ObjectReader.from_reader(self, data_reader, table_reader)
                    self.objects[obj.path_id] = obj
        else:
            # Pre-allocated for the worst case (every object excluded), then
            # trimmed to the real count below — see _EXCLUDED_OBJECT_DTYPE's
            # own comment for why this is a NumPy array and not a Python list.
            excluded_buf = np.empty(object_count, dtype=_EXCLUDED_OBJECT_DTYPE)
            excluded_count = 0
            for count, chunk in batches:
                if chunk is not None:
                    excluded = self._read_object_batch(data_reader, chunk, count, type_filter)
                    excluded_buf[excluded_count:excluded_count + len(excluded)] = excluded
                    excluded_count += len(excluded)
                    continue
                for _ in range(count):
                    obj, excluded = ObjectReader.from_reader_filtered(self, data_reader, type_filter, table_reader)
                    if obj is not None:
                        self.objects[obj.path_id] = obj
                    else:
                        excluded_buf[excluded_count] = excluded
                        excluded_count += 1
            self._excluded_objects = excluded_buf[:excluded_count] if excluded_count else None

        # Read Scripts
        if header.version >= 11:
            script_count = reader.read_int()
            self.script_types = [LocalSerializedObjectIdentifier(header, reader) for _ in range(script_count)]

        # Read Externals
        externals_count = reader.read_int()
        self.externals = [FileIdentifier(header, reader) for _ in range(externals_count)]

        if header.version >= 20:
            ref_type_count = reader.read_int()
            self.ref_types = [SerializedType(reader, self, True) for _ in range(ref_type_count)]

        if config.SERIALIZED_FILE_PARSE_TYPETREE is False:
            self._enable_type_tree = False

        if header.version >= 5:
            self.userInformation = reader.read_string_to_null()

        # read the asset_bundles to get the containers
        for obj in self.objects.values():
            if obj.type == ClassIDType.AssetBundle:
                self.assetbundle = obj.parse_as_object()
                self._container = ContainerHelper(self.assetbundle)
                break
        else:
            self.assetbundle = None
            self._container = ContainerHelper([])

    @property
    def container(self):
        return self._container

    def load_dependencies(self, possible_dependencies: Optional[list] = None):
        """Load all external dependencies.

        Parameters
        ----------
        possible_dependencies : list
            List of possible dependencies for cases
            where the target file is not listed as external.
        """
        for file_id in self.externals:
            self._load_dependency(file_id.path)

        if possible_dependencies is None:
            return

        for dependency in possible_dependencies:
            try:
                self._load_dependency(dependency)
            except FileNotFoundError:
                pass

    def _load_dependency(self, name: str):
        """Loads a dependency, preferring the copy that sits next to THIS file: when
        several folders of a game folder load each ship a same-named file (Folder A and
        Folder B both with resources.assets.resS), the one beside the file that needs it
        is the right one — not whichever a recursive search finds first."""
        import os
        env = self.environment
        src = env.source_path_of(self) if hasattr(env, "source_path_of") else None
        if src and name and not os.path.isabs(name):
            near = os.path.join(os.path.dirname(src), name)
            default = os.path.join(env.path or "", name)
            if os.path.isfile(near) and os.path.normcase(os.path.abspath(near)) != os.path.normcase(os.path.abspath(default)):
                if not env.is_file_loaded(near):
                    return env.load_file(near, is_dependency=True)
                return None  # already loaded (folder mode): pick_cab_alternative finds it
        return env.load_file(name, is_dependency=True)

    _OBJECT_TABLE_BATCH = 65536  # records per in-memory batch (~1.5 MB)
    _OBJECT_TABLE_BULK_MIN = 256  # below this the plain per-record path is just as fast

    def _object_table_batches(self, reader, header, object_count: int, in_memory: bool = False):
        """Yields (record_count, chunk) pairs covering the object table. chunk is the bytes of a batch of
        records (decoded by _read_object_batch), or None meaning "read the records from `reader` itself"
        (the old behaviour: loose files — already memory-mapped — small tables, and record layouts where a
        record is not a whole number of aligned bytes). The real `reader` is left exactly where the old
        per-record loop would have left it (end of the table)."""
        from ..helpers.bundle_inspector import _object_record_size
        from ..streams.EndianBinaryReader import EndianBinaryReader_Streamable

        raw_size = None
        if object_count >= self._OBJECT_TABLE_BULK_MIN and (in_memory or isinstance(reader, EndianBinaryReader_Streamable)):
            size, needs_align = _object_record_size(header.version, bool(self.big_id_enabled))
            # tightly packed records only: with a pad per record (v15/16 with is_stripped) the alignment
            # inside a copied batch would depend on its absolute offset — those keep the plain path
            if not needs_align or size % 4 == 0:
                raw_size = size
                if needs_align:
                    reader.align_stream()  # what the first record's own align_stream() would do

        if raw_size is None:
            yield object_count, None
            return

        remaining = object_count
        while remaining > 0:
            count = min(remaining, self._OBJECT_TABLE_BATCH)
            chunk = reader.read_bytes(count * raw_size)
            if len(chunk) != count * raw_size:
                raise ValueError(
                    f"object table truncated: {len(chunk)} of {count * raw_size} bytes (version {header.version})"
                )
            yield count, chunk
            remaining -= count

    def _object_table_dtype(self, header) -> np.dtype:
        """One object-table record as a packed numpy layout — the same fields, widths and order
        ObjectReader.from_reader() reads one by one (and _object_record_size() counts)."""
        e = header.endian
        version = header.version
        fields = [
            ("path_id", e + ("i8" if (self.big_id_enabled or version >= 14) else "i4")),
            ("byte_start", e + ("i8" if version >= 22 else "u4")),
            ("byte_size", e + "u4"),
            ("type_id", e + "i4"),
        ]
        if version < 16:
            fields.append(("class_id", e + "u2"))
        if version < 11:
            fields.append(("is_destroyed", e + "u2"))
        if 11 <= version < 17:
            fields.append(("script_type_index", e + "i2"))
        if version in (15, 16):
            fields.append(("is_stripped", "i1"))
        return np.dtype(fields)

    def _read_object_batch(self, reader, chunk, count: int, type_filter) -> np.ndarray:
        """Decodes `count` object-table records at once and adds the kept ones to self.objects — the
        same ObjectReaders, in the same order, with the same side effects as calling
        ObjectReader.from_reader() / from_reader_filtered() once per record (verified against the
        per-record path on every sample game). Python then only builds the kept ObjectReaders; a
        record a type filter skips never becomes a Python object (returned as _EXCLUDED_OBJECT_DTYPE
        records). Lego Party: 4.37 M records were ~15 s of the load, field by field."""
        header = self.header
        version = header.version
        types = self.types
        dtype = self._object_table_dtype(header)
        if dtype.itemsize * count != len(chunk):
            raise ValueError(
                f"object table record size mismatch: {dtype.itemsize} x {count} != {len(chunk)} bytes "
                f"(version {version})"
            )
        recs = np.frombuffer(chunk, dtype=dtype, count=count)
        type_ids = recs["type_id"]
        uniq_types, inverse = np.unique(type_ids, return_inverse=True)

        if version < 16:
            def serialized_type_of(type_id):
                return next((typ for typ in types if typ.class_id == type_id), None)
            class_ids = recs["class_id"].astype(np.int64)
        else:
            stypes = [types[int(t)] for t in uniq_types]     # IndexError for a bad id, like the per-record read
            class_ids = np.array([typ.class_id for typ in stypes], dtype=np.int64)[inverse]

            def serialized_type_of(type_id):
                return types[type_id]

        if 11 <= version < 17:
            # the per-record read sets serialized_type.script_type_index for every record: the last one wins
            reversed_first = np.unique(type_ids[::-1], return_index=True)[1]
            last_index = count - 1 - reversed_first
            for i in sorted(int(x) for x in last_index):
                typ = serialized_type_of(int(type_ids[i]))
                if typ:
                    typ.script_type_index = int(recs["script_type_index"][i])

        byte_starts = recs["byte_start"].astype(np.int64) + header.data_offset
        if type_filter is not None:
            keep = np.isin(class_ids, np.fromiter(type_filter, dtype=np.int64, count=len(type_filter)))
            drop = ~keep
            excluded = np.empty(int(drop.sum()), dtype=_EXCLUDED_OBJECT_DTYPE)
            if len(excluded):
                excluded["path_id"] = recs["path_id"][drop]
                excluded["type_id"] = type_ids[drop]
                excluded["class_id"] = class_ids[drop]
                excluded["is_destroyed"] = recs["is_destroyed"][drop] if version < 11 else 0
                excluded["is_stripped"] = recs["is_stripped"][drop] if version in (15, 16) else 0
                excluded["byte_start"] = byte_starts[drop]
                excluded["byte_size"] = recs["byte_size"][drop]
        else:
            keep = None
            excluded = np.empty(0, dtype=_EXCLUDED_OBJECT_DTYPE)

        def column(values):
            return (values if keep is None else values[keep]).tolist()

        path_ids = column(recs["path_id"])
        starts = column(byte_starts)
        sizes = column(recs["byte_size"])
        tids = column(type_ids)
        cids = column(class_ids)
        destroyed = column(recs["is_destroyed"]) if version < 11 else None
        stripped = column(recs["is_stripped"]) if version in (15, 16) else None

        objects = self.objects
        make = ObjectReader
        if destroyed is None and stripped is None and version >= 16:
            # the common case (every current format): the type id alone gives the class — everything per type is
            # resolved once, and the loop only builds the readers
            per_type = {}
            for tid in set(tids):
                typ = serialized_type_of(tid)
                per_type[tid] = (typ, typ.class_id, ClassIDType(typ.class_id))
            for path_id, tid, start, size in zip(path_ids, tids, starts, sizes):
                typ, cid, clz = per_type[tid]
                objects[path_id] = make(self, reader, path_id, tid, typ, cid, clz, start, size, None, None)
            return excluded

        info: dict = {}      # (type_id, class_id) -> (serialized_type, ClassIDType)
        for i, path_id in enumerate(path_ids):
            tid = tids[i]
            cid = cids[i]
            key = (tid, cid)
            found = info.get(key)
            if found is None:
                found = info[key] = (serialized_type_of(tid), ClassIDType(cid))
            objects[path_id] = make(
                self,
                reader,
                path_id,
                tid,
                found[0],
                cid,
                found[1],
                starts[i],
                sizes[i],
                destroyed[i] if destroyed is not None else None,
                stripped[i] if stripped is not None else None,
            )
        return excluded

    def set_version(self, string_version: str):
        self.unity_version = string_version
        if not string_version or string_version == "0.0.0":
            # weird case, but apparently can happen?
            # check "cant read Texture2D by 2020.3.13 f1 AssetBundle #77" for details
            if isinstance(self.parent, BundleFile.BundleFile):
                string_version = self.parent.version_engine
            if not string_version or string_version == "0.0.0":
                string_version = config.get_fallback_version()
        self.version = UnityVersion.from_str(string_version)

    def get_writeable_cab(self, name: str = "CAB-UnityPy_Mod.resS"):
        """
        Creates a new cab file in the bundle that contains the given data.
        This is usefull for asset types that use resource files.
        """
        if not isinstance(self.parent, (File.BundleFile.BundleFile, File.WebFile.WebFile)):
            return None

        cab = self.parent.get_writeable_cab(name)
        cab.path = f"archive:/{self.name}/{name}"
        if not any(cab.path == x.path for x in self.externals):
            # register as external
            class FileIdentifierFake:
                pass

            file_identifier = FileIdentifierFake()
            file_identifier.__class__ = FileIdentifier
            file_identifier.temp_empty = ""
            import uuid

            file_identifier.guid = uuid.uuid1().urn[-16:].encode("ascii")
            file_identifier.path = cab.path
            file_identifier.type = 0
            self.externals.append(file_identifier)

        return cab

    def close_source_handle(self) -> None:
        """Overrides File.close_source_handle() — see its own docstring for
        the general contract (call only after this file's own data has
        already been fully read/serialized; never makes the instance usable
        afterward).

        A LOOSE/standalone SerializedFile (self.parent is None, or at least
        not a BundleFile — a dependency loaded on its own is possible too)
        owns its .reader outright: nothing else in the process needs it once
        this file's own bytes are done being read, so it's safe to dispose
        directly. self.reader.dispose() is what actually releases the
        underlying OS handle — EndianBinaryReader_Memoryview.dispose()
        releases the memoryview onto its mmap (confirmed directly: an
        os.rename() self-probe that fails while the mmap is held succeeds
        immediately after this call, with no dependency on Python reference
        counts elsewhere in the process at all); EndianBinaryReader_
        Streamable.dispose() closes its underlying stream.

        A SerializedFile that's an entry INSIDE a bundle does NOT own its own
        reader — every entry of one bundle shares a single lazy
        BundleDataStream (see WindowReader's own docstring), so disposing
        here would pull the underlying handle out from under every OTHER
        entry of the same bundle that might still need it. That case is a
        deliberate no-op: BundleFile.close_source_handle() is what disposes
        the shared stream, once, at the bundle level — see its own
        docstring."""
        if isinstance(self.parent, BundleFile.BundleFile):
            return
        reader = getattr(self, "reader", None)
        if reader is not None and hasattr(reader, "dispose"):
            reader.dispose()

    def skipped_object(self, path_id: int) -> Optional[ObjectReader]:
        """An ObjectReader for an object a type-filtered load skipped (`_excluded_objects`), or None — for
        reading (e.g. a Sprite whose SpriteAtlas type was not loaded: the sprite's image lives on the atlas). It is
        NOT added to `objects` while only read: save() writes the skipped object back byte for byte. Its first
        write (set_raw_data, which patch()/save_typetree() end in) adopts it — adopt_skipped(). Cached per file."""
        records = self._excluded_objects
        if records is None or not len(records):
            return None
        cache = self.__dict__.setdefault("_skipped_readers", {})
        if path_id in cache:
            return cache[path_id]
        index = self.__dict__.get("_skipped_index")
        if index is None or index[0] is not records:    # built once per records array (adopt_skipped replaces it)
            order = np.argsort(records["path_id"], kind="stable")
            index = self.__dict__["_skipped_index"] = (records, records["path_id"][order], order)
        _records, ids, order = index
        i = int(np.searchsorted(ids, path_id))          # was a scan of every record per call: a model or scene
        if i >= len(ids) or int(ids[i]) != path_id:      # walk asks thousands of times
            return None
        rec = records[int(order[i])]
        header = self.header
        type_id, class_id = int(rec["type_id"]), int(rec["class_id"])
        if header.version < 16:
            serialized_type = next((t for t in self.types if t.class_id == type_id), None)
        else:
            serialized_type = self.types[type_id]
        reader = ObjectReader(
            self,
            self.reader,
            int(rec["path_id"]),
            type_id,
            serialized_type,
            class_id,
            ClassIDType(class_id),
            int(rec["byte_start"]),
            int(rec["byte_size"]),
            int(rec["is_destroyed"]) if header.version < 11 else None,
            int(rec["is_stripped"]) if header.version in (15, 16) else None,
        )
        cache[path_id] = reader
        return reader

    def adopt_skipped(self, path_id: int) -> Optional[ObjectReader]:
        """Moves an object a type-filtered load skipped into `objects` (the reader skipped_object() gives, so
        anything already holding it keeps the same object) and drops its `_excluded_objects` record: from then on
        save() writes it from the reader, like any loaded object — its edits are kept. Both must change
        together: listed in both, the object would be written twice. None if `path_id` is not skipped."""
        reader = self.skipped_object(path_id)
        if reader is None:
            return None
        records = self._excluded_objects
        keep = records["path_id"] != path_id
        self.objects[path_id] = reader
        self._excluded_objects = records[keep] if keep.any() else None
        self.__dict__.get("_skipped_readers", {}).pop(path_id, None)
        self.__dict__.setdefault("adopted_ids", set()).add(path_id)   # for callers that show it (a table row)
        return reader

    def save(self, packer: Optional[str] = None) -> bytes:
        # Real reported gap, now closed: this used to unconditionally refuse
        # to save any type_filter-loaded file at all ("Reupload the entire
        # file before saving") — forcing a choice between fast/light filtered
        # loading and ever being able to save it again. self._excluded_objects
        # (populated at load time — see SerializedFile.__init__'s type_filter
        # branch and _EXCLUDED_OBJECT_DTYPE's own comment) is what makes this
        # safe now: every object type_filter excluded gets written back
        # byte-for-byte from its ORIGINAL position in the source file, merged
        # in below alongside the real, possibly-edited ObjectReaders. A
        # partial load with NOTHING excluded (self._excluded_objects is None
        # either because type_filter was never used, or because it matched
        # every object present) needs no special handling at all — falls
        # through to the exact same loop as before.

        # 1. header -> has to be delayed until the very end
        # 2. data -> types, objects, scripts, ...

        # so write the data first
        header = self.header
        meta_writer = EndianBinaryWriter(endian=header.endian)
        data_writer = EndianBinaryWriter(endian=header.endian)

        if header.version >= 7:
            meta_writer.write_string_to_null(self.unity_version)

        if header.version >= 8:
            meta_writer.write_int(self._m_target_platform)

        if header.version >= 13:
            meta_writer.write_boolean(self._enable_type_tree)

        # ReadTypes
        meta_writer.write_int(len(self.types))
        for typ in self.types:
            typ.write(self, meta_writer, False)

        if 7 <= header.version < 14:
            meta_writer.write_int(self.big_id_enabled)

        # ReadObjects
        if self._excluded_objects is not None and len(self._excluded_objects):
            meta_writer.write_int(len(self.objects) + len(self._excluded_objects))
            real_entries = [(obj.path_id, obj) for obj in self.objects.values()]
            excluded_entries = [(int(rec["path_id"]), rec) for rec in self._excluded_objects]
            for _path_id, entry in sorted(real_entries + excluded_entries, key=lambda e: e[0]):
                if isinstance(entry, ObjectReader):
                    entry.write(header, meta_writer, data_writer)
                else:
                    _write_passthrough_object(entry, self, header, meta_writer, data_writer)
                data_writer.align_stream(8)
        else:
            meta_writer.write_int(len(self.objects))
            for obj in sorted(self.objects.values(), key=lambda x: x.path_id):
                obj.write(header, meta_writer, data_writer)
                data_writer.align_stream(8)

        # Read Scripts
        if header.version >= 11:
            meta_writer.write_int(len(self.script_types))
            for script_type in self.script_types:
                script_type.write(header, meta_writer)

        # Read Externals
        meta_writer.write_int(len(self.externals))
        for external in self.externals:
            external.write(header, meta_writer)

        if header.version >= 20:
            assert self.ref_types is not None
            meta_writer.write_int(len(self.ref_types))
            for ref_type in self.ref_types:
                ref_type.write(self, meta_writer, True)

        if header.version >= 5:
            assert self.userInformation is not None
            meta_writer.write_string_to_null(self.userInformation)

        # prepare header
        writer = EndianBinaryWriter()
        header_size = 16  # 4*4
        metadata_size = meta_writer.Length
        data_size = data_writer.Length
        if header.version >= 9:
            # 1 bool + 3 reserved + extra header 4 + 3*8
            header_size += 4 if header.version < 22 else 4 + 28
            data_offset = header_size + metadata_size
            # align data_offset
            data_offset += (16 - data_offset % 16) % 16
            file_size = data_offset + data_size
            if header.version < 22:
                writer.write_u_int(metadata_size)
                writer.write_u_int(file_size)
                writer.write_u_int(header.version)
                # reader.Position = header.file_size - header.metadata_size
                # so data follows right after this header -> after 32
                writer.write_u_int(data_offset)
                writer.write_boolean(">" == header.endian)
                writer.write_bytes(header.reserved)
            else:
                # old header
                writer.write_u_int(0)
                writer.write_u_int(0)
                writer.write_u_int(header.version)
                writer.write_u_int(0)
                writer.write_boolean(">" == header.endian)
                writer.write_bytes(header.reserved)
                writer.write_u_int(metadata_size)
                writer.write_long(file_size)
                writer.write_long(data_offset)
                writer.write_long(self.unknown)

            writer.write_bytes(meta_writer.bytes)
            writer.align_stream(16)
            writer.write_bytes(data_writer.bytes)

        else:
            metadata_size += 1  # endian boolean
            file_size = header_size + metadata_size + data_size
            writer.write_u_int(metadata_size)
            writer.write_u_int(file_size)
            writer.write_u_int(header.version)
            # reader.Position = header.file_size - header.metadata_size
            # so data follows right after this header -> after 32
            writer.write_u_int(32)
            writer.write_bytes(data_writer.bytes)
            writer.write_boolean(">" == header.endian)
            writer.write_bytes(meta_writer.bytes)

        return writer.bytes
    

def read_string(string_buffer_reader: EndianBinaryReader, value: int) -> str:
    is_offset = (value & 0x80000000) == 0
    if is_offset:
        string_buffer_reader.Position = value
        return string_buffer_reader.read_string_to_null()

    offset = value & 0x7FFFFFFF
    return get_common_strings().get(offset, str(offset))
