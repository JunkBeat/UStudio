from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Generic,
    List,
    Optional,
    Type,
    TypeVar,
    Union,
    cast,
)

from attrs import define

from ..classes import MonoBehaviour
from ..classes.ClassIDTypeToClassMap import ClassIDTypeToClassMap
from ..enums import ClassIDType
from ..exceptions import TypeTreeError
from ..helpers import TypeTreeHelper
from ..helpers.Tpk import get_typetree_node
from ..helpers.TypeTreeNode import TypeTreeNode
from ..streams import EndianBinaryReader, EndianBinaryWriter

if TYPE_CHECKING:
    from ..files.SerializedFile import SerializedFile, SerializedType

T = TypeVar("T")
NodeInput = Union[TypeTreeNode, List[Dict[str, Union[str, int]]]]

from typing import NamedTuple

class ObjectEntryInfo(NamedTuple):
    path_id: int
    byte_start: int
    byte_size: int
    type_id: int
    class_id: int


@define(
    slots=True,
)
class ObjectReader(Generic[T]):
    assets_file: SerializedFile
    reader: EndianBinaryReader
    path_id: int
    type_id: int
    serialized_type: Optional[SerializedType]
    class_id: int
    type: ClassIDType
    byte_start: int
    byte_size: int
    is_destroyed: Optional[int]
    is_stripped: Optional[int]
    data: Optional[bytes] = None
    _read_until: Optional[int] = None
    # Cache for parse_monobehaviour_head()'s generic-template result — see that
    # method's docstring for why this matters (resolve_object_name() and
    # resolve_script_name() used to each independently pay for this same parse).
    _mb_head_cache: Optional[MonoBehaviour] = None

    @property
    def version(self):
        return self.assets_file.version

    @property
    def version2(self):
        return self.assets_file.header.version

    @property
    def platform(self):
        return self.assets_file.target_platform

    # saves where the parser stopped
    # in case that not all data is read
    # and the obj.data is changed, the unknown data can be added again
    @classmethod
    def from_reader(
        cls, assets_file: SerializedFile, reader: EndianBinaryReader, data_reader: Optional[EndianBinaryReader] = None
    ) -> ObjectReader[Any]:
        # data_reader: where the object-table FIELDS are read from (SerializedFile's bulk table read hands in an
        # in-memory copy of a batch of records); the ObjectReader itself must keep the real `reader` for
        # reading the object's data later. None = read the fields from `reader`, as always.
        src = reader if data_reader is None else data_reader
        header = assets_file.header
        types = assets_file.types

        # AssetStudio ObjectInfo init
        if assets_file.big_id_enabled:
            path_id = src.read_long()
        elif header.version < 14:
            path_id = src.read_int()
        else:
            src.align_stream()
            path_id = src.read_long()

        if header.version >= 22:
            byte_start = src.read_long()
        else:
            byte_start = src.read_u_int()

        byte_start += header.data_offset
        byte_size = src.read_u_int()

        type_id = src.read_int()

        serialized_type = None
        if header.version < 16:
            class_id = src.read_u_short()
            for typ in types:
                if typ.class_id == type_id:
                    serialized_type = typ
                    break
        else:
            typ = types[type_id]
            serialized_type = typ
            class_id = typ.class_id

        clz_type = ClassIDType(class_id)

        is_destroyed = None
        if header.version < 11:
            is_destroyed = src.read_u_short()

        if 11 <= header.version < 17:
            script_type_index = src.read_short()
            if serialized_type:
                serialized_type.script_type_index = script_type_index

        is_stripped = None
        if header.version == 15 or header.version == 16:
            is_stripped = src.read_byte()

        return cls(
            assets_file,
            reader,
            path_id,
            type_id,
            serialized_type,
            class_id,
            clz_type,
            byte_start,
            byte_size,
            is_destroyed,
            is_stripped,
        )

    @classmethod
    def from_reader_filtered(
        cls, assets_file: SerializedFile, reader: EndianBinaryReader, type_filter,
        data_reader: Optional[EndianBinaryReader] = None,
    ) -> "tuple[ObjectReader[Any] | None, tuple | None]":
        """Same field layout/read order as from_reader() above — kept as an
        exact copy rather than a shared helper so from_reader()'s own hot
        path (type_filter is None, the overwhelmingly common case) stays
        byte-for-byte untouched and provably unaffected by this. Every
        field is read in the same order either way, since they're
        interleaved in the object table's byte stream and must be consumed
        to keep the reader position correct for the next record regardless
        of whether this particular object ends up kept.

        This is the direct fix for a real, present-day gap: previously,
        the "Filtered" load-time option (SerializedFile.__init__'s own
        `type_filter` branch below) discarded excluded objects only AFTER
        building a full ObjectReader for every single one — meaning
        Filtered mode never actually saved any load TIME, only final
        RAM/table-row count. Skipping construction (not the reads) for
        excluded objects is what actually makes Filtered mode faster to
        load, not just smaller once loaded.

        Returns (ObjectReader, None) for a kept object, or (None,
        excluded_record) for an excluded one — excluded_record is a plain
        (path_id, type_id, class_id, is_destroyed, is_stripped, byte_start,
        byte_size) tuple, deliberately NOT a full ObjectReader, so
        SerializedFile.__init__ can pack it into a compact NumPy array
        instead of paying full per-instance Python object cost for
        millions of objects nobody asked to load — see that array's own
        dtype/comment (SerializedFile.py) for why this matters at scale,
        and save()'s own comment for what it's actually FOR: writing a
        type-filtered load back out losslessly, byte-for-byte, for
        whatever wasn't touched, instead of refusing to save at all.
        is_destroyed/is_stripped are stored as 0 when this format version
        doesn't have them (never actually read back in that case either —
        save()'s write-back is gated by the same header.version checks
        used here, so the placeholder value is simply never reached)."""
        src = reader if data_reader is None else data_reader
        header = assets_file.header
        types = assets_file.types

        if assets_file.big_id_enabled:
            path_id = src.read_long()
        elif header.version < 14:
            path_id = src.read_int()
        else:
            src.align_stream()
            path_id = src.read_long()

        if header.version >= 22:
            byte_start = src.read_long()
        else:
            byte_start = src.read_u_int()

        byte_start += header.data_offset
        byte_size = src.read_u_int()

        type_id = src.read_int()

        serialized_type = None
        if header.version < 16:
            class_id = src.read_u_short()
            for typ in types:
                if typ.class_id == type_id:
                    serialized_type = typ
                    break
        else:
            typ = types[type_id]
            serialized_type = typ
            class_id = typ.class_id

        is_destroyed = None
        if header.version < 11:
            is_destroyed = src.read_u_short()

        if 11 <= header.version < 17:
            script_type_index = src.read_short()
            if serialized_type:
                serialized_type.script_type_index = script_type_index

        is_stripped = None
        if header.version == 15 or header.version == 16:
            is_stripped = src.read_byte()

        if class_id not in type_filter:
            return None, (
                path_id, type_id, class_id,
                is_destroyed if is_destroyed is not None else 0,
                is_stripped if is_stripped is not None else 0,
                byte_start, byte_size,
            )

        clz_type = ClassIDType(class_id)

        return cls(
            assets_file,
            reader,
            path_id,
            type_id,
            serialized_type,
            class_id,
            clz_type,
            byte_start,
            byte_size,
            is_destroyed,
            is_stripped,
        ), None

    def write(self, header, writer: EndianBinaryWriter, data_writer: EndianBinaryWriter):
        if self.assets_file.big_id_enabled:
            writer.write_long(self.path_id)
        elif header.version < 14:
            writer.write_int(self.path_id)
        else:
            writer.align_stream()
            writer.write_long(self.path_id)

        if self.data is not None:
            data = self.data
            # in some cases the parser doesn't read all of the object data
            # games might still require the missing data
            # so following code appends the missing data back to edited objects
            # -> following solution has let to some problems, so it will be removed for now
            # if self.type != ClassIDType.MonoBehaviour:
            #     end_pos = self.byte_start + self.byte_size
            #     if self._read_until and self._read_until != end_pos:
            #         self.reader.Position = self._read_until
            #         data += self.reader.read_bytes(end_pos - self._read_until)
        else:
            with self.reader.lock:
                self.reset()
                data = self.reader.read(self.byte_size)

        if header.version >= 22:
            writer.write_long(data_writer.Position)
        else:
            writer.write_u_int(data_writer.Position)

        writer.write_u_int(len(data))
        data_writer.write(data)

        writer.write_int(self.type_id)

        if header.version < 16:
            writer.write_u_short(self.class_id)

        if header.version < 11:
            assert self.is_destroyed is not None
            writer.write_u_short(self.is_destroyed)

        if 11 <= header.version < 17:
            assert self.serialized_type is not None
            writer.write_short(self.serialized_type.script_type_index)

        if header.version == 15 or header.version == 16:
            assert self.is_stripped is not None
            writer.write_byte(self.is_stripped)

    def set_raw_data(self, data: bytes):
        skipped = getattr(self.assets_file, "_skipped_readers", None)
        if skipped and skipped.get(self.path_id) is self:
            # A reader SerializedFile.skipped_object() made (an object a type-filtered load left out): without this
            # the edit would be silently lost — save() writes a skipped object from its original bytes. Adopted, it
            # is an ordinary loaded object and is saved like any edited one. (Kept on the file, not as a field: a
            # field costs 8 bytes on every reader — 3.1 M of them on a big game.)
            self.assets_file.adopt_skipped(self.path_id)
        self.data = data
        if self.assets_file:
            self.assets_file.mark_changed()

    def get_class(self) -> Union[Type[T], None]:
        return ClassIDTypeToClassMap.get(self.type)  # type: ignore

    _PEEK_WINDOW_START = 256
    _PEEK_WINDOW_GROWTH = 8

    def _read_head(self, node: TypeTreeNode, wrap: bool = False):
        """Parse a BOUNDED node (a peek node, or the MonoBehaviour head template: it ends long
        before the object does) reading only as many bytes as it needs.

        read_typetree() hands the native parser the object's WHOLE byte range, which for a
        name/script lookup means pulling every byte of a texture/mesh/audio object through the
        Python stream layers just to read a field at the very start. Here a small window is tried
        first and grown x8 until the parse fits: the parser consumes sequentially and raises when
        it runs past the window, and a parse that succeeds consumed exactly the same bytes as
        the whole-object one — so the result is identical, only cheaper. Falls back to the
        ordinary whole-object read when the window would reach the object's size anyway, and for
        an object with a pending edit (its bytes are already in memory)."""
        size = self._PEEK_WINDOW_START
        if self.data is None:
            stream = getattr(self.reader, "stream", None)
            read_at = getattr(stream, "read_at", None)  # a bundle entry's window: positional, no cursor
            if read_at is not None:
                start = self.byte_start + getattr(self.reader, "BaseOffset", 0)
                while True:
                    size = min(size, self.byte_size)
                    try:
                        ret = TypeTreeHelper.read_typetree_from_bytes(
                            read_at(start, size),
                            node,
                            self.reader.endian,
                            as_dict=not wrap,
                            assetsfile=self.assets_file,
                        )
                    except Exception:
                        if size >= self.byte_size:
                            break  # the whole object was not enough: let the ordinary read report why
                        size *= self._PEEK_WINDOW_GROWTH
                        continue
                    if wrap:
                        ret.set_object_reader(self)  # type: ignore
                    return ret
            else:
                while size < self.byte_size:
                    try:
                        with self.reader.lock:
                            self.reset()
                            ret = TypeTreeHelper.read_typetree(
                                node,
                                self.reader,
                                as_dict=not wrap,
                                assetsfile=self.assets_file,
                                byte_size=size,
                                check_read=False,
                            )
                    except Exception:
                        size *= self._PEEK_WINDOW_GROWTH
                        continue
                    if wrap:
                        ret.set_object_reader(self)  # type: ignore
                    return ret
        return self.read_typetree(nodes=node, wrap=wrap, check_read=False)

    def peek_name(self) -> Union[str, None]:
        """Peeks the name of the object without reading/parsing the whole object."""
        node = self._get_typetree_node()
        peek_node = node.get_name_peek_node()
        if peek_node:
            node, key = peek_node
            return self._read_head(node)[key]
        else:
            return None

    def peek_tail(self, size: int) -> bytes:
        """The object's LAST `size` bytes, without parsing or reading anything else (a pending
        edit's own bytes if the object was patched). For questions the end of an object can answer
        by itself — e.g. whether a trailing string field is empty — on objects whose body is far
        too big to read just for that (a 66 MB inline Mesh)."""
        if self.data is not None:
            return bytes(self.data[-size:])
        size = min(size, self.byte_size)
        with self.reader.lock:
            pos = self.Position
            self.reader.Position = self.byte_start + self.byte_size - size
            ret = self.reader.read(size)
            self.Position = pos
        return ret

    def peek_field(self, field_names: tuple) -> Any:
        """Reads just one top-level field (by name, or the first match among
        several candidate names) without parsing the object's full body — same
        bounded-node technique as peek_name(), generalized via
        TypeTreeNode.get_field_peek_node(). Returns None if the object's schema
        doesn't declare any of field_names at all (a legitimate "field not
        present" case, e.g. an older format without this field, not a parse
        failure)."""
        node = self._get_typetree_node()
        peek_node = node.get_field_peek_node(field_names)
        if not peek_node:
            return None
        node, key = peek_node
        return self._read_head(node)[key]

    def peek_dict(self, field_names: tuple) -> Optional[dict]:
        """Reads SEVERAL top-level fields (every name in field_names that the
        schema actually declares) in one bounded parse, without paying for
        whatever comes after the last of them — TypeTreeNode.
        get_last_field_peek_node()'s own docstring explains why this needs its
        own "stop at the LAST match" node rather than reusing peek_field()'s
        first-match one (the requested fields aren't guaranteed to be adjacent
        or declared in the same relative order field_names was given in).
        Returns None only if the schema declares NONE of field_names at all;
        otherwise a dict with exactly the subset of field_names that were
        actually present (never a KeyError for one that wasn't — same
        "missing field is a legitimate outcome" contract peek_field() already
        has, just applied per-key instead of to the whole call)."""
        node = self._get_typetree_node()
        peek_node = node.get_last_field_peek_node(field_names)
        if not peek_node:
            return None
        node, matched = peek_node
        full = self._read_head(node)
        return {name: full[name] for name in matched}

    @property
    def container(self):
        env = self.assets_file.environment
        if env is not None:
            env._build_container_index()
        return self.assets_file._container.path_dict.get(self.path_id)

    @property
    def Position(self):
        return self.reader.Position

    @Position.setter
    def Position(self, pos):
        self.reader.Position = pos

    def reset(self):
        self.reader.Position = self.byte_start

    def read(self, check_read: bool = True) -> T:
        return self.read_typetree(wrap=True, check_read=check_read)  # type: ignore

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __getattr__(self, item: str):
        if hasattr(self.reader, item):
            return getattr(self.reader, item)

    def __repr__(self):
        return "<%s %s>" % (self.__class__.__name__, self.type.name)

    ###################################################
    #
    #           Typetree Stuff
    #
    ###################################################

    def dump_typetree_structure(
        self,
        nodes: Optional[NodeInput] = None,
        indent: str = "  ",
    ) -> str:
        node = self._get_typetree_node(nodes)
        return node.dump_structure(indent=indent)

    def read_typetree(
        self,
        nodes: Optional[NodeInput] = None,
        wrap: bool = False,
        check_read: bool = True,
    ) -> Union[dict, T]:
        node = self._get_typetree_node(nodes)
        if self.data is not None:
            # An edit is pending (patch()/save_typetree()/set_raw_data() already
            # ran) — read it back from self.data instead of self.reader/
            # byte_start, which still point at the file's ORIGINAL, unedited
            # bytes on disk (self.reader is never touched by an edit — only
            # write() reads self.data, when this object is actually saved to a
            # file). Without this, re-reading an object right after editing it
            # (a fresh selection, the JSON dump tab, another patch() building on
            # the previous one, ...) would silently show the pre-edit content
            # again. self.data is exactly one object's own bytes starting at
            # its own position 0 (write_typetree() always writes into a fresh
            # EndianBinaryWriter — see save_typetree()), so a fresh reader over
            # it needs no offset, and len(self.data) — not the stale
            # self.byte_size from before the edit — is the size to read/check
            # against, since an edit can grow or shrink the object.
            data_reader = EndianBinaryReader(self.data, endian=self.reader.endian)
            ret = TypeTreeHelper.read_typetree(
                node,
                data_reader,
                as_dict=not wrap,
                assetsfile=self.assets_file,
                byte_size=len(self.data),
                check_read=check_read,
            )
        else:
            # self.reader is shared by every ObjectReader of this SerializedFile
            # (and, for a bundle-internal file, by every entry of the whole
            # bundle beneath that) — the whole seek-then-many-sequential-reads
            # sequence below must be atomic, not just the seek, or a concurrent
            # read of a DIFFERENT object on another thread can desync this
            # one's stream position mid-parse. See WindowReader's docstring.
            with self.reader.lock:
                self.reset()
                ret = TypeTreeHelper.read_typetree(
                    node,
                    self.reader,
                    as_dict=not wrap,
                    assetsfile=self.assets_file,
                    byte_size=self.byte_size,
                    check_read=check_read,
                )
        if wrap:
            ret.set_object_reader(self)  # type: ignore
        return ret  # type: ignore

    def save_typetree(
        self,
        tree: Union[dict, T],
        nodes: Optional[NodeInput] = None,
        writer: Optional[EndianBinaryWriter] = None,
    ):
        node = self._get_typetree_node(nodes)
        if not writer:
            writer = EndianBinaryWriter(endian=self.reader.endian)
        TypeTreeHelper.write_typetree(tree, node, writer, self.assets_file)
        data = writer.bytes
        self.set_raw_data(data)
        return data

    def get_raw_data(self) -> bytes:
        # Whole save-position/seek/read/restore-position sequence held atomic against
        # concurrent reads of other objects sharing this same reader — see read_typetree().
        with self.reader.lock:
            pos = self.Position
            self.reset()
            ret = self.reader.read_bytes(self.byte_size)
            self.Position = pos
        return ret

    def _get_typetree_node(
        self,
        node: Optional[NodeInput] = None,
    ) -> TypeTreeNode:
        if isinstance(node, TypeTreeNode):
            return node
        elif isinstance(node, list):
            return TypeTreeNode.from_list(node)
        elif node is not None:
            raise ValueError("nodes must be a list[dict] or TypeTreeNode")

        if self.serialized_type:
            node = self.serialized_type.node
        if not node:
            node = get_typetree_node(self.class_id, self.version)
            if node.m_Type == "MonoBehaviour":
                try:
                    node = self.generate_monobehaviour_node()
                    # Every MonoBehaviour object referencing this exact script
                    # (same type_id -> same serialized_type entry, for any format
                    # version new enough to track script_type_index per type
                    # entry) shares this same node — writing it back here means
                    # only the FIRST such object per script ever pays for
                    # generation (native generator call + head-parse +
                    # script-deref); every other object of that script hits the
                    # cheap `self.serialized_type.node` read above instead. Safe
                    # even when serialized_type turns out to be object-specific
                    # rather than shared (older/edge-case formats) — it's still
                    # unambiguously the correct node for THIS object's own
                    # type_id either way.
                    if self.serialized_type is not None:
                        self.serialized_type.node = node
                except ValueError:
                    pass
            elif self.serialized_type is not None:
                # Same reasoning as the MonoBehaviour writeback above,
                # generalized to every other type — get_typetree_node()
                # always resolves to the exact same node for every object
                # sharing this serialized_type (same type_id => same
                # class_id, and version is a per-FILE property, identical
                # for every object in it), so caching it here is unconditionally
                # safe, not just a MonoBehaviour-specific trick.
                #
                # Real profiled gap this closes: on a real shipped game with
                # TypeTree data stripped from the file (SerializedType.node
                # never embedded — common for release builds), every
                # non-MonoBehaviour object paid for a fresh
                # get_typetree_node(class_id, version) call on every single
                # peek_name()/peek_field() — cached at the function level
                # (functools.cache) so it never re-parses the TPK blob, but
                # the call itself still costs a real, measured amount
                # (UnityVersion.__hash__/__eq__ plus the cache dict lookup)
                # at millions-of-objects scale — confirmed via cProfile on a
                # real ~78M-object fixture, where _get_typetree_node() alone
                # accounted for over 3.2M calls building just ~690K table
                # rows. This was already fixed for MonoBehaviour; every
                # other type fell through to the expensive path every time.
                self.serialized_type.node = node
        if not node:
            raise TypeTreeError("There are no TypeTree nodes for this object.")
        return node

    # UnityPy 2 syntax early implementation
    def parse_as_object(self, node: Optional[NodeInput] = None, check_read: bool = True) -> T:
        return self.read_typetree(nodes=node, wrap=True, check_read=check_read)  # type: ignore

    def parse_as_dict(self, node: Optional[NodeInput] = None, check_read: bool = True) -> dict[str, Any]:
        return self.read_typetree(nodes=node, wrap=False, check_read=check_read)  # type: ignore

    def patch(
        self,
        obj: Union[dict, T],
        nodes: Optional[NodeInput] = None,
        writer: Optional[EndianBinaryWriter] = None,
    ):
        return self.save_typetree(obj, nodes=nodes, writer=writer)

    # MonoBehaviour specific methods
    def parse_monobehaviour_head(self, mb_node: Optional[TypeTreeNode] = None) -> MonoBehaviour:
        # Cache only the common case: the generic head-only template (mb_node
        # omitted) on an object with no pending edit. resolve_object_name()
        # (via peek_name() -> generate_monobehaviour_node()) and
        # resolve_script_name() (via peek_mb_name()) both hit exactly this path
        # for the same object — before this cache, each paid for its own
        # read_typetree() call (real I/O + parsing) to get the same head fields.
        # Skipped whenever self.data is set (patch()/set_raw_data() already ran)
        # so a freshly-edited object's head is always read from the new data,
        # never a stale pre-edit cache.
        use_cache = mb_node is None and self.data is None
        if use_cache and self._mb_head_cache is not None:
            return self._mb_head_cache

        if mb_node is None:
            mb_node = get_typetree_node(ClassIDType.MonoBehaviour, self.version)

        mb = cast(MonoBehaviour, self._read_head(mb_node, wrap=True))
        if use_cache:
            self._mb_head_cache = mb
        return mb

    def generate_monobehaviour_node(self, mb_node: Optional[TypeTreeNode] = None) -> TypeTreeNode:
        env = self.assets_file.environment
        generator = env.typetree_generator
        if generator is None:
            raise ValueError("MonoBehaviour detected, but no typetree_generator set to the environment!")

        monobehaviour = self.parse_monobehaviour_head(mb_node)
        script = monobehaviour.m_Script.deref_parse_as_object()

        if script.m_Namespace != "":
            fullname = f"{script.m_Namespace}.{script.m_ClassName}"
        else:
            fullname = script.m_ClassName

        node = generator.get_nodes_up(script.m_AssemblyName, fullname)
        if node:
            return node
        else:
            raise ValueError(f"Failed to generate MonoBehaviour node for {fullname} of {script.m_AssemblyName}!")


__all__ = [
    "ObjectReader",
]
