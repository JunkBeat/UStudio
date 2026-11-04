from __future__ import annotations

import builtins
import re
import sys
import threading
from contextlib import nullcontext
from io import BufferedReader, IOBase
from struct import Struct, unpack
from types import MethodType
from typing import Any, Callable, ClassVar, Dict, List, Literal, Optional, Tuple, Union

reNot0 = re.compile(b"(.*?)\x00", re.S)
# read_string_to_null reads ahead this much at a time (most strings — file paths, type names — are far shorter)
_STRING_CHUNK = 256

# Stand-in for readers/streams that don't share their cursor with anyone else (e.g. a
# loose file's own EndianBinaryReader_Memoryview) — .lock is always safe to use in a
# `with` statement even when there's really nothing to serialize against.
_NULL_LOCK = nullcontext()

# read_view() returns a copy (bytes) up to this many bytes, a zero-copy memoryview above it — see its docstring.
READ_VIEW_COPY_LIMIT = 64 * 1024

SYS_ENDIAN = "<" if sys.byteorder == "little" else ">"
Endianess = Literal["<", ">"]

# generate unpack and unpack_from functions
TYPE_PARAM_SIZE_LIST = [
    ("short", "h"),
    ("u_short", "H"),
    ("int", "i"),
    ("u_int", "I"),
    ("long", "q"),
    ("u_long", "Q"),
    ("half", "e"),
    ("float", "f"),
    ("double", "d"),
]

MEMORY_FUNCTIONS: Dict[Endianess, Dict[str, Callable[["EndianBinaryReader_Memoryview"], Any]]] = {"<": {}, ">": {}}
STREAM_FUNCTIONS: Dict[Endianess, Dict[str, Callable[["EndianBinaryReader_Streamable"], Any]]] = {"<": {}, ">": {}}


class EndianBinaryReader:
    Length: int
    Position: int
    BaseOffset: int
    _endian: Endianess
    _function_map: ClassVar[Dict[Endianess, Dict[str, Callable]]]

    def __new__(
        cls,
        item: Union[bytes, bytearray, memoryview, IOBase, str],
        endian: Endianess = ">",
        offset: int = 0,
    ):
        if isinstance(item, (bytes, bytearray, memoryview)):
            obj = super(EndianBinaryReader, cls).__new__(EndianBinaryReader_Memoryview)  # type: ignore
        else:
            try:
                item_view = memoryview(item)
            except TypeError:
                if isinstance(item, IOBase):
                    obj = super(EndianBinaryReader, cls).__new__(EndianBinaryReader_Streamable)  # type: ignore
                elif isinstance(item, str):
                    obj = super(EndianBinaryReader, cls).__new__(EndianBinaryReader_Streamable_LocalFile)  # type: ignore
                elif isinstance(item, EndianBinaryReader):
                    item = item.stream if isinstance(item, EndianBinaryReader_Streamable) else item.view
                    return EndianBinaryReader(item, endian, offset)
                elif hasattr(item, "read"):
                    if hasattr(item, "seek") and hasattr(item, "tell"):
                        obj = super(EndianBinaryReader, cls).__new__(EndianBinaryReader_Streamable)
                    else:
                        item = item.read()
                        obj = super(EndianBinaryReader, cls).__new__(EndianBinaryReader_Memoryview)
                else:
                    raise TypeError("Unsupported type for EndianBinaryReader: %s" % type(item))
            else:
                item = item_view
                obj = super(EndianBinaryReader, cls).__new__(EndianBinaryReader_Memoryview)  # type: ignore
        return obj

    def __init__(self, item, endian: Endianess = ">", offset: int = 0):
        self._endian = ""  # type: ignore
        self.endian = endian
        self.BaseOffset = offset
        self.Position = 0

    @property
    def endian(self) -> Endianess:
        return self._endian

    @endian.setter
    def endian(self, value: Endianess):
        if value not in ("<", ">"):
            raise ValueError("Invalid endian")
        if value != self._endian:
            for func_name, func in self._function_map[value].items():
                setattr(self, func_name, MethodType(func, self))
            self._endian = value

    @property
    def bytes(self) -> builtins.bytes:
        # implemented by Streamable and Memoryview versions
        return b""

    @property
    def lock(self):
        """A lock guarding this reader's cursor against concurrent access from
        another thread — overridden by EndianBinaryReader_Streamable, whose
        underlying stream may be a WindowReader shared by every ObjectReader of one
        SerializedFile (see WindowReader's docstring). Other variants (e.g. a loose
        file's own Memoryview reader) aren't shared this way, so there's nothing to
        serialize against."""
        return _NULL_LOCK

    def read(self, size: Optional[int] = -1, /) -> builtins.bytes:
        # implemented by Streamable and Memoryview versions
        return b""

    # NEW METHOD
    def read_view(self, size: int) -> Union[builtins.bytes, "memoryview"]:
        """A slice without an extra copy where possible.
        For streamable readers a copy can't be avoided — data is read from disk."""
        return self.read(size)

    def read_byte(self) -> int:
        return unpack(self.endian + "b", self.read(1))[0]

    def read_u_byte(self) -> int:
        return unpack(self.endian + "B", self.read(1))[0]

    def read_bytes(self, num: int) -> builtins.bytes:
        return self.read(num)

    def read_short(self) -> int:
        return unpack(self.endian + "h", self.read(2))[0]

    def read_int(self) -> int:
        return unpack(self.endian + "i", self.read(4))[0]

    def read_long(self) -> int:
        return unpack(self.endian + "q", self.read(8))[0]

    def read_u_short(self) -> int:
        return unpack(self.endian + "H", self.read(2))[0]

    def read_u_int(self) -> int:
        return unpack(self.endian + "I", self.read(4))[0]

    def read_u_long(self) -> int:
        return unpack(self.endian + "Q", self.read(8))[0]

    def read_float(self) -> float:
        return unpack(self.endian + "f", self.read(4))[0]

    def read_double(self) -> float:
        return unpack(self.endian + "d", self.read(8))[0]

    def read_boolean(self) -> bool:
        return bool(unpack(self.endian + "?", self.read(1))[0])

    def read_string(self, size: Optional[int] = None) -> str:
        if size is None:
            return self.read_string_to_null()
        else:
            raw = self.read_bytes(size)
            return raw.decode("utf8", "surrogateescape")

    def read_string_to_null(self, max_length: int = 32767) -> str:
        # Reads ahead in chunks and finds the terminator, instead of one read(1) per byte: inside a bundle every
        # read goes through the locked block reader, and a load of Lego Party spent ~6 s on 26 k strings (mostly
        # the external file paths). Same results as the byte loop it replaces, its two edge cases included: with no
        # terminator in the first max_length bytes it consumes max_length bytes and returns max_length - 1 of them;
        # at the end of the data without a terminator it returns all but the last byte read.
        pos = self.Position
        length = self.Length
        out = bytearray()
        while pos != length:
            chunk = self.read(min(_STRING_CHUNK, length - pos))
            if type(chunk) is not bytes:
                chunk = bytes(chunk)        # some readers hand out memoryviews (no .find)
            if not chunk:
                raise ValueError("Unterminated string: %r" % bytes(out))
            room = max_length - len(out)            # bytes the byte loop could still have read
            end = chunk.find(b"\0", 0, room)
            if end != -1:
                out += chunk[:end]
                self.Position = pos + end + 1
                return out.decode("utf8", "surrogateescape")
            if len(chunk) >= room:
                out += chunk[:room]
                self.Position = pos + room
                return out[:-1].decode("utf8", "surrogateescape")
            out += chunk
            pos += len(chunk)
            self.Position = pos
        return out[:-1].decode("utf8", "surrogateescape")

    def read_aligned_string(self) -> str:
        length = self.read_int()
        if 0 < length <= self.Length - self.Position:
            string_data = bytes(self.read_bytes(length))
            result = string_data.decode("utf8", "surrogateescape")
            self.align_stream()
            return result
        return ""

    def align_stream(self, alignment=4):
        self.Position += (alignment - self.Position % alignment) % alignment

    def read_byte_array(self) -> builtins.bytes:
        return self.read(self.read_int())

    def read_array(self, command: Callable, length: int) -> list:
        return [command() for _ in range(length)]

    def read_array_struct(self, param: str, length: Optional[int] = None) -> tuple:
        if length is None:
            length = self.read_int()
        struct = Struct(f"{self.endian}{length}{param}")
        return struct.unpack(self.read(struct.size))

    def read_boolean_array(self, length: Optional[int] = None) -> Tuple[bool, ...]:
        return self.read_array_struct("?", length)

    def read_u_byte_array(self, length: Optional[int] = None) -> Tuple[int, ...]:
        return self.read_array_struct("B", length)

    def read_u_short_array(self, length: Optional[int] = None) -> Tuple[int, ...]:
        return self.read_array_struct("h", length)

    def read_short_array(self, length: Optional[int] = None) -> Tuple[int, ...]:
        return self.read_array_struct("H", length)

    def read_int_array(self, length: Optional[int] = None) -> Tuple[int, ...]:
        return self.read_array_struct("i", length)

    def read_u_int_array(self, length: Optional[int] = None) -> Tuple[int, ...]:
        return self.read_array_struct("I", length)

    def read_long_array(self, length: Optional[int] = None) -> Tuple[int, ...]:
        return self.read_array_struct("q", length)

    def read_u_long_array(self, length: Optional[int] = None) -> Tuple[int, ...]:
        return self.read_array_struct("Q", length)

    def read_float_array(self, length: Optional[int] = None) -> Tuple[float, ...]:
        return self.read_array_struct("f", length)

    def read_double_array(self, length: Optional[int] = None) -> Tuple[float, ...]:
        return self.read_array_struct("d", length)

    def read_string_array(self) -> List[str]:
        return self.read_array(self.read_aligned_string, self.read_int())

    def real_offset(self) -> int:
        """Returns offset in the underlying file.
        (Not working with unpacked streams.)
        """
        return self.BaseOffset + self.Position

    def read_the_rest(self, obj_start: int, obj_size: int) -> builtins.bytes:
        """Returns the rest of the current reader bytes."""
        return self.read_bytes(obj_size - (self.Position - obj_start))

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            new_pos = offset
        elif whence == 1:
            new_pos = self.Position + offset
        elif whence == 2:
            new_pos = self.Length + offset
        else:
            raise ValueError("Invalid whence value")
        if new_pos < 0:
            raise ValueError("New position is before the start of the stream")
        self.Position = new_pos
        return self.Position

    def tell(self) -> int:
        return self.Position
    

class EndianBinaryReader_Memoryview(EndianBinaryReader):
    __slots__ = ("view", "_endian", "BaseOffset", "Position", "Length", "_lock")
    _endian: Endianess
    view: memoryview
    _function_map = MEMORY_FUNCTIONS

    def __init__(self, view, endian: Endianess = ">", offset: int = 0):
        super().__init__(view, endian=endian, offset=offset)
        self.view = memoryview(view)
        self.Length = len(view)
        # Real, reproduced bug this closes — see the .lock property override just
        # below for the full explanation: the base class's assumption that a loose
        # file's Memoryview reader "isn't shared this way, so there's nothing to
        # serialize against" is simply wrong once this reader is used from more
        # than one thread, which this app genuinely does (GUI-thread MonoBehaviour
        # resolution vs. a background task-queue job touching the same
        # SerializedFile). self.Position is real, shared, mutable cursor state.
        self._lock = threading.RLock()

    @property
    def bytes(self):
        return self.view.tobytes()

    @property
    def lock(self):
        """Overrides the base class's `_NULL_LOCK` — this reader instance IS shared
        by every ObjectReader of one SerializedFile for a loose (non-bundle) file,
        exactly the same way a WindowReader is shared for a bundle-internal one (see
        ObjectReader.read_typetree()'s own docstring: "the whole seek-then-many-
        sequential-reads sequence below must be atomic"). The base class's original
        premise — that a Memoryview reader "isn't shared this way" — held for a
        single-threaded caller, but this app calls into it concurrently (the GUI
        thread's own MonoBehaviour/script-name resolution racing a background
        task-queue job, e.g. SDF font-atlas generation, against the SAME already-
        loaded Environment). Reproduced directly without this lock: concurrent reads
        against a real loose-file fixture produced corrupted values (EOFError:
        read_str out of bounds; ValueError: Negative length read from TypeTree;
        wrong PathIDs) even after locking find_file()/TypeTreeGenerator — this was
        the remaining, third unlocked point in the same chain."""
        return self._lock

    def dispose(self) -> None:
        self.view.release()
    
    def read(self, size: Optional[int] = -1, /):
        if not size:
            return b""
        if size == -1:
            size = self.Length - self.Position
        ret = self.view[self.Position : self.Position + size]
        self.Position += size
        return ret.tobytes()

    # NEW METHOD
    def read_view(self, size: int) -> Union[builtins.bytes, memoryview]:
        """A slice without copying (valid as long as self.view stays alive) — but only for a LARGE one.

        A zero-copy slice of a file's mapping keeps the whole mapping open for as long as it lives anywhere,
        and the file stays locked with it (no overwrite, no delete). The big reads (a compressed block) are
        handed straight to a decompressor and dropped, but a tiny slice (a type-tree string table, a hash) is
        exactly what a closure, a cache or a traceback ends up keeping by accident: a real overwrite save failed
        with "file held by this program" because three 16-byte slices of one bundle were kept alive that way.
        Copying a few KB costs nothing, so below the limit the caller gets plain bytes that cannot pin anything."""
        ret = self.view[self.Position : self.Position + size]
        self.Position += size
        if size <= READ_VIEW_COPY_LIMIT:
            return ret.tobytes()
        return ret

    def read_array_struct(self, param: str, length: Optional[int] = None) -> tuple:
        if length is None:
            length = self.read_int()
        struct = Struct(f"{self.endian}{length}{param}")
        value = struct.unpack_from(self.view, self.Position)
        self.Position += struct.size
        return value

    def read_aligned_string(self) -> str:
        length = self.read_int()
        if 0 < length <= self.Length - self.Position:
            string_data = self.read_bytes(length)
            result = bytes(string_data).decode("utf8", "surrogateescape")
            self.align_stream()
            return result
        return ""

    def read_string_to_null(self, max_length: int = 32767) -> str:
        match = reNot0.search(self.view, self.Position, self.Position + max_length)
        if not match:
            if self.Position + max_length >= self.Length:
                raise Exception("String not terminated")
            else:
                return bytes(self.read_bytes(max_length)).decode("utf8", "surrogateescape")
        ret = match[1].decode("utf8", "surrogateescape")
        self.Position = match.end()
        return ret


class EndianBinaryReader_Streamable(EndianBinaryReader):
    __slots__ = ("stream", "_endian", "BaseOffset")
    stream: BufferedReader
    _function_map = STREAM_FUNCTIONS

    def __init__(self, stream: BufferedReader, endian: Endianess = ">", offset: int = 0):
        self.stream = stream
        super().__init__(stream, endian=endian, offset=offset)
        self.read = self.stream.read

    @property
    def Position(self) -> int:
        return self.stream.tell() - self.BaseOffset

    @Position.setter
    def Position(self, value: int):
        if value < 0:
            raise ValueError("Position cannot be negative")
        self.stream.seek(value + self.BaseOffset)

    @property
    def Length(self):  # type: ignore
        pos = self.Position
        length = self.stream.seek(0, 2) - self.BaseOffset
        self.Position = pos
        return length

    @property
    def bytes(self):
        last_pos = self.Position
        self.Position = 0
        ret = self.read(self.Length)
        self.Position = last_pos  # type: ignore
        return ret

    @property
    def lock(self):
        """Forwards to the underlying stream's lock, when it has one (a WindowReader
        does — see its docstring for why this matters). Lets ObjectReader wrap its
        whole get-position/seek/read/restore-position sequence in one `with
        self.reader.lock:` instead of racing step-by-step against other ObjectReaders
        of the same file that share this exact reader instance."""
        return getattr(self.stream, "lock", None) or _NULL_LOCK

    def dispose(self):
        self.stream.close()
        pass


class EndianBinaryReader_Streamable_LocalFile(EndianBinaryReader_Streamable):
    def __init__(self, path: str, endian: Endianess = ">", offset: int = 0):
        super().__init__(open(path, "rb"), endian=endian, offset=offset)

    def __del__(self):
        self.stream.close()


class WindowReader(IOBase):
    """Zero-copy window over a lazy underlying reader (typically a bundle's shared
    blocksReader). IMPORTANT: File.read_files() constructs one WindowReader per bundle
    entry, but they all wrap the SAME underlying `reader` — and within one entry,
    every ObjectReader of the resulting SerializedFile shares this one WindowReader
    too (via SerializedFile.reader). Both layers are therefore mutable state shared
    across threads: this instance's own `_position` cursor (shared by every
    ObjectReader of one file) and the underlying `reader`'s cursor (shared by every
    WindowReader/file of one bundle). `lock` (held for the full body of seek()/read(),
    and re-acquired by callers like ObjectReader wrapping a multi-step
    save-seek-read-restore sequence — safe since it's an RLock) makes this instance's
    own cursor safe; `self._reader.lock` (acquired here too, nested) makes the
    cross-file, bundle-wide cursor safe as well."""

    __slots__ = ("_reader", "_start", "_length", "_position", "lock")

    def __init__(self, reader: EndianBinaryReader, start: int, length: int):
        self._reader = reader
        self._start = start
        self._length = length
        self._position = 0
        self.lock = threading.RLock()

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._position

    def seek(self, offset: int, whence: int = 0) -> int:
        with self.lock:
            if whence == 0:
                new_pos = offset
            elif whence == 1:
                new_pos = self._position + offset
            elif whence == 2:
                new_pos = self._length + offset
            else:
                raise ValueError("Invalid whence value")
            if new_pos < 0:
                raise ValueError("New position is before the start of the stream")
            self._position = min(new_pos, self._length)
            return self._position

    def read_at(self, offset: int, size: int) -> builtins.bytes:
        """`size` bytes at `offset` of this window, leaving the cursor (this window's and the
        shared underlying reader's) exactly where it was. Same bytes as seek(offset)+read(size)."""
        if offset < 0 or offset >= self._length or size <= 0:
            return b""
        size = min(size, self._length - offset)
        inner = getattr(self._reader, "stream", None)
        if inner is not None and hasattr(inner, "read_at"):
            return inner.read_at(self._start + offset, size)
        with self._reader.lock:
            saved = self._reader.Position
            try:
                self._reader.Position = self._start + offset
                return self._reader.read(size)
            finally:
                self._reader.Position = saved

    def read(self, size: Optional[int] = -1) -> builtins.bytes:
        with self.lock:
            if size is None or size < 0:
                size = self._length - self._position
            if self._position >= self._length or size <= 0:
                return b""
            size = min(size, self._length - self._position)
            # Nested (RLock) acquisition of the shared underlying reader's own lock:
            # makes the seek-then-read pair against it atomic as a whole, not just each
            # call individually — see the class docstring and CLAUDE.md's bug writeup
            # for why a per-call-only lock here would still race across different
            # WindowReaders of the same bundle.
            with self._reader.lock:
                self._reader.Position = self._start + self._position
                self._position += size
                return self._reader.read(size)


for endian_s in ("<", ">"):
    for reader_type_name, struct_type_char in TYPE_PARAM_SIZE_LIST:
        func_name = f"read_{reader_type_name}"
        struct = Struct(f"{endian_s}{struct_type_char}")

        def memory_read_func(self: EndianBinaryReader_Memoryview, /, struct=struct):
            value = struct.unpack_from(self.view, self.Position)[0]
            self.Position += struct.size
            return value

        def stream_read_func(self: EndianBinaryReader_Streamable, /, struct=struct):
            return struct.unpack(self.stream.read(struct.size))[0]

        MEMORY_FUNCTIONS[endian_s][func_name] = memory_read_func
        STREAM_FUNCTIONS[endian_s][func_name] = stream_read_func
