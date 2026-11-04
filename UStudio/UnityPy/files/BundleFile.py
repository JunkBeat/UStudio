# TODO: implement encryption for saving files
import io
import os
import re
import shutil
import tempfile
from bisect import bisect_right
from collections import OrderedDict, namedtuple
from typing import Optional, Union, cast

from .. import config
from ..enums import ArchiveFlags, ArchiveFlagsOld, CompressionFlags
from ..helpers import ArchiveStorageManager, CompressionHelper
from ..helpers.UnityVersion import UnityVersion
from ..streams import EndianBinaryReader, EndianBinaryWriter
from . import File

BlockInfo = namedtuple("BlockInfo", "uncompressedSize compressedSize flags")
DirectoryInfoFS = namedtuple("DirectoryInfoFS", "offset size flags path")
reVersion = re.compile(r"(\d+)\.(\d+)\.(\d+)\w.+")

import threading

_CACHE_LOCK = threading.Lock()
GLOBAL_BLOCK_CACHE: "OrderedDict[tuple[str, int], bytes]" = OrderedDict()
GLOBAL_BLOCK_CACHE_TOTAL_BYTES = 0

def clear_bundle_cache(bundle_id: Optional[str] = None) -> None:
    """Clears the global cache of decompressed blocks.
    Without an argument — clears entirely (e.g. when closing the whole Environment).
    With bundle_id — only entries for that specific bundle (before it's reopened)."""
    global GLOBAL_BLOCK_CACHE_TOTAL_BYTES
    with _CACHE_LOCK:
        if bundle_id is None:
            GLOBAL_BLOCK_CACHE.clear()
            GLOBAL_BLOCK_CACHE_TOTAL_BYTES = 0
            return
        for key in [k for k in GLOBAL_BLOCK_CACHE if k[0] == bundle_id]:
            GLOBAL_BLOCK_CACHE_TOTAL_BYTES -= len(GLOBAL_BLOCK_CACHE.pop(key))


class BundleDataStream(io.RawIOBase):
    def __init__(self, reader, block_info, data_start, length, decompress_func, bundle_id):
        self.reader = reader
        self.block_info = block_info
        self.data_start = data_start
        self.length = length
        self.position = 0
        self.decompress_func = decompress_func
        self.bundle_id = bundle_id
        self._uncompressed_offsets = [0]
        self._compressed_offsets = [0]
        for block in block_info:
            self._uncompressed_offsets.append(self._uncompressed_offsets[-1] + block.uncompressedSize)
            self._compressed_offsets.append(self._compressed_offsets[-1] + block.compressedSize)
        # self._last_block / self._last_block_index — REMOVED
        # This one BundleDataStream instance (and the single underlying `reader`
        # handle it wraps) is shared by every WindowReader of every internal entry of
        # this bundle — read()/seek() below each hold this for their whole body, and
        # WindowReader.read() additionally holds it across its own seek+read pair (see
        # WindowReader's docstring), so concurrent access from different entries can't
        # interleave and hand back the wrong offset's bytes.
        self.lock = threading.RLock()

    def close(self):
        # io.RawIOBase's default close() only marks THIS stream object closed —
        # it has no idea self.reader (the actual mmap/file-backed
        # EndianBinaryReader every WindowReader of this bundle ultimately reads
        # through) exists at all, so it never released the real OS handle on
        # its own. That's the actual fix for "overwriting a bundle's own
        # source file fails while this app still has it open" — see
        # BundleFile.close_source_handle()'s docstring for the full chain and
        # why it's safe to call only once every entry's data has already been
        # read out of this stream.
        reader = getattr(self, "reader", None)
        if reader is not None and hasattr(reader, "dispose"):
            reader.dispose()
        super().close()

    def _decompress_block(self, block_index: int) -> bytes:
        global GLOBAL_BLOCK_CACHE_TOTAL_BYTES
        key = (self.bundle_id, block_index)

        with _CACHE_LOCK:
            cached_block = GLOBAL_BLOCK_CACHE.get(key)
            if cached_block is not None:
                GLOBAL_BLOCK_CACHE.move_to_end(key)
                return cached_block

        block = self.block_info[block_index]
        compressed_offset = self.data_start + self._compressed_offsets[block_index]
        self.reader.Position = compressed_offset
        compressed_data = (
            self.reader.read_view(block.compressedSize)
            if hasattr(self.reader, "read_view")
            else self.reader.read(block.compressedSize)
        )
        decompressed = self.decompress_func(compressed_data, block.uncompressedSize, block.flags, block_index)

        with _CACHE_LOCK:
            cache_size = len(decompressed)
            while GLOBAL_BLOCK_CACHE and GLOBAL_BLOCK_CACHE_TOTAL_BYTES + cache_size > config.BUNDLE_BLOCK_CACHE_SIZE:
                _, evicted = GLOBAL_BLOCK_CACHE.popitem(last=False)
                GLOBAL_BLOCK_CACHE_TOTAL_BYTES -= len(evicted)
            GLOBAL_BLOCK_CACHE[key] = decompressed
            GLOBAL_BLOCK_CACHE_TOTAL_BYTES += cache_size

        return decompressed

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset: int, whence: int = io.SEEK_SET):
        with self.lock:
            if whence == io.SEEK_SET:
                new_pos = offset
            elif whence == io.SEEK_CUR:
                new_pos = self.position + offset
            elif whence == io.SEEK_END:
                new_pos = self.length + offset
            else:
                raise ValueError("Invalid whence value")
            if new_pos < 0:
                raise ValueError("New position is before the start of the stream")
            self.position = min(new_pos, self.length)
            return self.position

    def _block_index(self, pos: int) -> int:
        index = bisect_right(self._uncompressed_offsets, pos) - 1
        return max(0, min(index, len(self.block_info) - 1))

    def read_at(self, offset: int, size: int) -> bytes:
        """`size` bytes at absolute `offset` WITHOUT touching this stream's cursor (no seek/tell
        pair, no restore), for callers that only need a few bytes at a known place — the cursor
        protocol costs more than the read itself for a small one. Same bytes seek()+read() give,
        clamped at the end of the stream the same way."""
        with self.lock:
            if offset < 0 or offset >= self.length or size <= 0:
                return b""
            size = min(size, self.length - offset)
            block_index = self._block_index(offset)
            block_data = self._decompress_block(block_index)
            offset_in_block = offset - self._uncompressed_offsets[block_index]
            if offset_in_block + size <= len(block_data):
                return block_data[offset_in_block : offset_in_block + size]
            result = bytearray(size)
            written = 0
            while written < size:
                block_index = self._block_index(offset + written)
                block_data = self._decompress_block(block_index)
                offset_in_block = offset + written - self._uncompressed_offsets[block_index]
                chunk = min(size - written, self.block_info[block_index].uncompressedSize - offset_in_block)
                result[written : written + chunk] = block_data[offset_in_block : offset_in_block + chunk]
                written += chunk
            return bytes(result)

    def read(self, size: int = -1) -> bytes:
        with self.lock:
            if size is None or size < 0:
                size = self.length - self.position
            if self.position >= self.length or size <= 0:
                return b""
            size = min(size, self.length - self.position)

            block_index = self._block_index(self.position)
            block_start = self._uncompressed_offsets[block_index]
            block_data = self._decompress_block(block_index)
            offset_in_block = self.position - block_start
            if offset_in_block + size <= len(block_data):
                self.position += size
                return block_data[offset_in_block : offset_in_block + size]

            result = bytearray(size)
            written = 0
            while written < size:
                block_index = self._block_index(self.position)
                block_start = self._uncompressed_offsets[block_index]
                block = self.block_info[block_index]
                block_data = self._decompress_block(block_index)
                offset_in_block = self.position - block_start
                chunk_size = min(size - written, block.uncompressedSize - offset_in_block)
                result[written : written + chunk_size] = block_data[offset_in_block : offset_in_block + chunk_size]
                self.position += chunk_size
                written += chunk_size

            return bytes(result)


class FlaggedBytesSource:
    """Lightweight "source .bytes + .flags" wrapper for use in
    BundleFile.files during rebuild (save()/save_to_file()) when an entry is NOT
    touched (not re-imported) and doesn't need to be materialized into memory
    ahead of time — only once save_fs()/save_fs_to_file() themselves get to it.

    Needed because flags is stored on the entry's File wrapper object (e.g.
    a not-yet-fully-parsed SerializedFile stub from an object_count_only=True
    scan), while the raw bytes are only reachable through its .reader — but the
    reader itself (EndianBinaryReader_Memoryview/_Streamable) declares __slots__,
    so you can't just tack .flags onto it directly. This wrapper holds a reference
    to the .bytes source and pairs it with .flags, without copying or reading
    anything until .bytes is first accessed."""

    __slots__ = ("_source", "flags")

    def __init__(self, source, flags: int = 0):
        self._source = source
        self.flags = flags

    @property
    def bytes(self) -> bytes:
        return self._source.bytes

    @property
    def Length(self) -> int:
        return self._source.Length

    def write_to_stream(self, out_stream, chunk_size: int = 8 * 1024 * 1024, should_cancel=None, progress_callback=None) -> int:
        """Streams the source's contents into out_stream in chunks of
        chunk_size, WITHOUT materializing the whole entry in memory at once (unlike
        .bytes). Matters for individual internal archive files that can themselves
        be very large (e.g. a large .resS in a game with thousands of internal
        files, where .bytes for just that one entry is already a multi-gigabyte
        spike in RAM by itself, regardless of the rest of the rebuild being
        streaming). should_cancel (if given) is checked between chunks — closes a
        known gap in save_fs_to_file(), where cancellation previously couldn't
        trigger WHILE reading one giant entry, only between entries.
        progress_callback(written_so_far, this_entry_total) — likewise needed so
        one long-running entry doesn't look "frozen": without it, the "write" phase's
        progress only updated BETWEEN entries, and if one of them by itself took
        several minutes (rather than being the sum of many small ones), the user
        would see no movement at all for several minutes (real report: "reached
        99%, then nothing happened for a long time")."""
        stream = self._source
        stream.Position = 0
        total = stream.Length
        remaining = total
        written = 0
        report = CompressionHelper.ThrottledProgress(progress_callback)
        while remaining > 0:
            if should_cancel is not None and should_cancel():
                raise CompressionHelper.RebuildCancelled()
            chunk = stream.read(min(chunk_size, remaining))
            if not chunk:
                break
            out_stream.write(chunk)
            written += len(chunk)
            remaining -= len(chunk)
            report(written, total)
        report(total, total, force=True)
        return written


class FilePathBytesSource:
    """Like FlaggedBytesSource above, but backed by a file PATH ON DISK rather than an
    existing archive entry — for save()/save_to_file() callers replacing an entry with
    an external file (e.g. CabBrowserDialog's Import/Import All) without reading it into
    memory upfront. Reading is deferred to save_fs()/save_fs_to_file() itself, exactly
    like FlaggedBytesSource defers reading an untouched entry.

    This existing specifically because an earlier version of the Import All caller built
    an EndianBinaryWriter(full_file_bytes) per replaced entry UPFRONT, before the
    background rebuild even started — on a real ~35GB import (see CLAUDE.md's hard-case
    fixture) that alone exhausted available memory with a bare MemoryError (whose str()
    is empty, so it surfaced as a blank error dialog) before the disk-backed rebuild,
    whose entire point is to avoid exactly this, ever got to run."""

    __slots__ = ("path", "flags", "_length")

    def __init__(self, path: str, flags: int = 0):
        self.path = path
        self.flags = flags
        self._length = None

    @property
    def Length(self) -> int:
        if self._length is None:
            self._length = os.path.getsize(self.path)
        return self._length

    @property
    def bytes(self) -> bytes:
        with open(self.path, "rb") as f:
            return f.read()

    def write_to_stream(self, out_stream, chunk_size: int = 8 * 1024 * 1024, should_cancel=None, progress_callback=None) -> int:
        total = self.Length
        written = 0
        report = CompressionHelper.ThrottledProgress(progress_callback)
        with open(self.path, "rb") as f:
            while written < total:
                if should_cancel is not None and should_cancel():
                    raise CompressionHelper.RebuildCancelled()
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                out_stream.write(chunk)
                written += len(chunk)
                report(written, total)
        report(total, total, force=True)
        return written


class BundleFile(File.File):
    format: int
    is_changed: bool
    signature: str
    version_engine: str
    version_player: str
    dataflags: Union[ArchiveFlags, ArchiveFlagsOld]
    decryptor: Optional[ArchiveStorageManager.ArchiveStorageDecryptor] = None
    _uses_block_alignment: bool = False

    def __init__(
        self,
        reader: EndianBinaryReader,
        parent: File,
        name: Optional[str] = None,
        progress_callback=None,
        object_count_only=False,
        type_filter=None,
        **kwargs,
    ):
        super().__init__(parent=parent, name=name, **kwargs)
        self.decompressed_size = 0  # filled in by read_fs regardless of mode, at no extra cost
        signature = self.signature = reader.read_string_to_null()
        self.version = reader.read_u_int()
        self.version_player = reader.read_string_to_null()
        self.version_engine = reader.read_string_to_null()

        if signature == "UnityArchive":
            raise NotImplementedError("BundleFile - UnityArchive")
        elif signature in ["UnityWeb", "UnityRaw"]:
            if self.version == 6:
                m_DirectoryInfo, blocksReader = self.read_fs(reader)
            else:
                m_DirectoryInfo, blocksReader = self.read_web_raw(reader)
        elif signature == "UnityFS":
            m_DirectoryInfo, blocksReader = self.read_fs(reader)
        else:
            raise NotImplementedError(f"Unknown Bundle signature: {signature}")

        # Kept for close_source_handle() below — every internal entry's own
        # reader chain reaches this same object (see File.read_files()/
        # WindowReader), but there was previously no direct way to reach it
        # FROM the BundleFile itself without walking through an arbitrary
        # entry's private reader/stream chain.
        self.blocksReader = blocksReader

        self.read_files(
            blocksReader, m_DirectoryInfo, progress_callback=progress_callback,
            object_count_only=object_count_only, type_filter=type_filter,
        )

    def read_web_raw(self, reader: EndianBinaryReader):
        # def read_header_and_blocks_info(self, reader:EndianBinaryReader):
        version = self.version
        if version >= 4:
            self._hash = reader.read_bytes(16)
            self.crc = reader.read_u_int()

        minimumStreamedBytes = reader.read_u_int()  # noqa: F841
        headerSize = reader.read_u_int()
        numberOfLevelsToDownloadBeforeStreaming = reader.read_u_int()  # noqa: F841
        levelCount = reader.read_int()
        reader.Position += 4 * 2 * (levelCount - 1)

        compressedSize = reader.read_u_int()
        uncompressedSize = reader.read_u_int()  # noqa: F841

        if version >= 2:
            completeFileSize = reader.read_u_int()  # noqa: F841

        if version >= 3:
            fileInfoHeaderSize = reader.read_u_int()  # noqa: F841

        reader.Position = headerSize

        uncompressedBytes = reader.read_bytes(compressedSize)
        if self.signature == "UnityWeb":
            uncompressedBytes = CompressionHelper.decompress_lzma(uncompressedBytes, True)

        blocksReader = EndianBinaryReader(uncompressedBytes, offset=headerSize)
        nodesCount = blocksReader.read_int()
        m_DirectoryInfo = [
            File.DirectoryInfo(
                blocksReader.read_string_to_null(),  # path
                blocksReader.read_u_int(),  # offset
                blocksReader.read_u_int(),  # size
            )
            for _ in range(nodesCount)
        ]

        return m_DirectoryInfo, blocksReader

    def read_fs(self, reader: EndianBinaryReader):
        size = reader.read_long()  # noqa: F841

        # header
        compressedSize = reader.read_u_int()
        uncompressedSize = reader.read_u_int()
        dataflagsValue = reader.read_u_int()

        # UnityWeb version 6
        if self.signature != "UnityFS":
            reader.read_byte()

        version = self.parse_version()
        # https://issuetracker.unity3d.com/issues/files-within-assetbundles-do-not-start-on-aligned-boundaries-breaking-patching-on-nintendo-switch
        # Unity CN introduced encryption before the alignment fix was introduced.
        # Unity CN used the same flag for the encryption as later on the alignment fix,
        # so we have to check the version to determine the correct flag set.
        if (
            version < (2020,)
            or (version[0] == 2020 and version < (2020, 3, 34))
            or (version[0] == 2021 and version < (2021, 3, 2))
            or (version[0] == 2022 and version < (2022, 1, 1))
        ):
            self.dataflags = ArchiveFlagsOld(dataflagsValue)
        else:
            self.dataflags = ArchiveFlags(dataflagsValue)

        if self.dataflags & self.dataflags.UsesAssetBundleEncryption:
            self.decryptor = ArchiveStorageManager.ArchiveStorageDecryptor(reader)

        # if header version is 7 or later we need to align the reader
        # for 2019.4.15 and later, version should be 7 and aligned
        # but some games in these versions somehow has version 6 while aligned
        if self.version >= 7 or (version[0] == 2019 and version >= (2019, 4, 15)):
            reader.align_stream(16)
            self._uses_block_alignment = True

        start = reader.Position
        if self.dataflags & ArchiveFlags.BlocksInfoAtTheEnd:  # kArchiveBlocksInfoAtTheEnd
            reader.Position = reader.Length - compressedSize
            blocksInfoBytes = reader.read_bytes(compressedSize)
            reader.Position = start
        else:  # 0x40 kArchiveBlocksAndDirectoryInfoCombined
            blocksInfoBytes = reader.read_bytes(compressedSize)

        blocksInfoBytes = self.decompress_data(blocksInfoBytes, uncompressedSize, self.dataflags)
        blocksInfoReader = EndianBinaryReader(blocksInfoBytes, offset=start)

        uncompressedDataHash = blocksInfoReader.read_bytes(16)  # noqa: F841
        blocksInfoCount = blocksInfoReader.read_int()

        m_BlocksInfo = [
            BlockInfo(
                blocksInfoReader.read_u_int(),  # uncompressedSize
                blocksInfoReader.read_u_int(),  # compressedSize
                blocksInfoReader.read_u_short(),  # flags
            )
            for _ in range(blocksInfoCount)
        ]

        nodesCount = blocksInfoReader.read_int()
        m_DirectoryInfo = [
            DirectoryInfoFS(
                blocksInfoReader.read_long(),  # offset
                blocksInfoReader.read_long(),  # size
                blocksInfoReader.read_u_int(),  # flags
                blocksInfoReader.read_string_to_null(),  # path
            )
            for _ in range(nodesCount)
        ]

        if m_BlocksInfo:
            self._block_info_flags = m_BlocksInfo[0].flags

        if isinstance(self.dataflags, ArchiveFlags) and self.dataflags & ArchiveFlags.BlockInfoNeedPaddingAtStart:
            reader.align_stream(16)

        data_start = reader.Position
        uncompressed_size = sum(b.uncompressedSize for b in m_BlocksInfo)
        self.decompressed_size = uncompressed_size
        data_stream = BundleDataStream(
            reader,
            m_BlocksInfo,
            data_start,
            uncompressed_size,
            self.decompress_data,
            bundle_id=self._cache_id,
        )

        blocksReader = EndianBinaryReader(
            data_stream,
            offset=0,
        )

        return m_DirectoryInfo, blocksReader

    def close_source_handle(self) -> None:
        """Overrides File.close_source_handle() — see its own docstring for
        the general contract (call only after this file's own data has
        already been fully read/serialized, e.g. after .save() — never makes
        the instance usable afterward).

        Unlike a loose SerializedFile, a BundleFile's OWN internal entries
        don't each own a separate reader — every one of them reads through
        self.blocksReader (an EndianBinaryReader wrapping either a lazy
        BundleDataStream, for the common "UnityFS"/read_fs case, or an
        already-fully-decompressed in-memory buffer, for the legacy
        UnityWeb/UnityRaw read_web_raw case — see read_fs/read_web_raw's own
        docstrings). Disposing self.blocksReader is therefore the single
        release point for the WHOLE bundle regardless of which of those two
        shapes it is: EndianBinaryReader_Streamable.dispose() (the read_fs
        case) closes the BundleDataStream, which — via the close() override
        added there — cascades down to disposing ITS OWN underlying
        mmap/file-backed reader; EndianBinaryReader_Memoryview.dispose() (the
        read_web_raw case) releases its own memoryview directly, no
        cascading needed since it's already the outermost stream.

        Safe to call exactly once, after every internal entry this bundle's
        own .save() needed has already been read — which prepare_overwrite()
        guarantees by calling this only after _save_bytes() returns."""
        blocks_reader = getattr(self, "blocksReader", None)
        if blocks_reader is not None and hasattr(blocks_reader, "dispose"):
            blocks_reader.dispose()

    def save(self, packer=None):
        """
        Rewrites the BundleFile and returns it as bytes object.

        packer:
            can be either one of the following strings
            or tuple consisting of (data_flag, block_info_flag)
            allowed strings:
                none - no compression, default, safest bet
                lz4 - lz4 compression
                lz4hc - lz4hc compression
                lzma - lzma compression
                original - uses the original flags
        """
        # file_header
        #     signature         (string_to_null)
        #     format            (int)
        #     version_player    (string_to_null)
        #     version_engine    (string_to_null)
        writer = EndianBinaryWriter()

        writer.write_string_to_null(self.signature)
        writer.write_u_int(self.version)
        writer.write_string_to_null(self.version_player)
        writer.write_string_to_null(self.version_engine)

        if self.signature == "UnityArchive":
            raise NotImplementedError("BundleFile - UnityArchive")
        elif self.signature in ["UnityWeb", "UnityRaw"]:
            if self.version == 6:
                self.save_fs(writer, 64, 64)
            else:
                self.save_web_raw(writer)
        elif self.signature == "UnityFS":
            if not packer or packer == "none":
                self.save_fs(writer, 64, 64)
            elif packer == "original":
                self.save_fs(
                    writer,
                    data_flag=self.dataflags,
                    block_info_flag=self._block_info_flags,
                )
            elif packer == "lz4":
                self.save_fs(writer, data_flag=194, block_info_flag=2)
            elif packer == "lz4hc":
                self.save_fs(writer, data_flag=195, block_info_flag=3)
            elif packer == "lzma":
                self.save_fs(writer, data_flag=65, block_info_flag=1)
            elif isinstance(packer, tuple):
                self.save_fs(writer, *packer)
            else:
                raise NotImplementedError("UnityFS - Packer:", packer)
        clear_bundle_cache(self._cache_id)
        return writer.bytes

    def save_fs(self, writer: EndianBinaryWriter, data_flag: int, block_info_flag: int):
        # header
        # compressed blockinfo (block details & directionary)
        # compressed assets

        # 0b1000000 / 0b11000000 | 64 / 192 - uncompressed
        # 0b11000010 | 194 - lz4
        # 0b11000011 | 195 - lz4hc
        # block_info_flag

        # 0 / 0b1000000 | 0 / 64 - uncompressed
        # 0b1   | 1 - lzma
        # 0b10  | 2 - lz4
        # 0b11  | 3 - lz4hc
        # 0b100 | 4 - lzham [not implemented]
        # data_flag

        # header:
        #     bundle_size       (long)
        #     compressed_size   (int)
        #     uncompressed_size (int)
        #     flag              (int)
        #     ?padding?         (bool)
        #   This will be written at the end,
        #   because the size can only be calculated after the data compression,

        # block_info:
        #     *flag & 0x80 ? at the end : right after header
        #     *decompression via flag & 0x3F
        #     *read compressed_size -> uncompressed_size
        #     0x10 offset
        #     *read blocks infos of the data stream
        #     count                 (int)
        #     (
        #         uncompressed_size (uint)
        #         compressed_size   (uint)
        #         flag              (short)
        #     )
        #     *decompression via info.flag & 0x3F

        #     *afterwards the file positions
        #     file_count    (int)
        #     (
        #         offset    (long)
        #         size      (long)
        #         flag      (int)
        #         name      (string_to_null)
        #     )

        # file list & file data
        # prep nodes and build up block data
        data_writer = EndianBinaryWriter()
        files = [
            (
                name,
                f.flags,
                # hasattr(f, "bytes") — not a strict isinstance — so this also accepts
                # FlaggedBytesSource (see the class above): a lightweight wrapper with
                # no upfront read, used by the UI when rebuilding an archive so that
                # untouched entries don't get materialized in memory twice.
                data_writer.write_bytes(
                    f.bytes if hasattr(f, "bytes") else f.save()
                ),
            )
            for name, f in self.files.items()
        ]

        file_data = data_writer.bytes
        data_writer.dispose()

        # remove encryption flag, as encryption isn't done
        if block_info_flag & self.dataflags.UsesAssetBundleEncryption:
            block_info_flag ^= self.dataflags.UsesAssetBundleEncryption
        if data_flag & self.dataflags.UsesAssetBundleEncryption:
            data_flag ^= self.dataflags.UsesAssetBundleEncryption

        file_data, block_info = CompressionHelper.chunk_based_compress(file_data, block_info_flag)

        # write the block_info
        # uncompressedDataHash
        block_writer = EndianBinaryWriter(b"\x00" * 0x10)
        # data block info
        block_writer.write_int(len(block_info))
        for block_uncompressed_size, block_compressed_size, block_flag in block_info:
            # uncompressed size
            block_writer.write_u_int(block_uncompressed_size)
            # compressed size
            block_writer.write_u_int(block_compressed_size)
            # flag
            block_writer.write_u_short(block_flag)

        # file block info
        if not data_flag & 0x40:
            raise NotImplementedError("UnityPy always writes DirectoryInfo, so data_flag must include 0x40")
        # file count
        block_writer.write_int(len(files))
        offset = 0
        for f_name, f_flag, f_len in files:
            # offset
            block_writer.write_long(offset)
            # size
            block_writer.write_long(f_len)
            offset += f_len
            # flag
            block_writer.write_u_int(f_flag)
            # name
            block_writer.write_string_to_null(f_name)

        # compress the block data
        block_data = block_writer.bytes
        block_writer.dispose()

        uncompressed_block_data_size = len(block_data)

        switch = data_flag & 0x3F
        if switch in CompressionHelper.COMPRESSION_MAP:
            block_data = CompressionHelper.COMPRESSION_MAP[switch](block_data)
        else:
            raise NotImplementedError(f"No compression function in the CompressionHelper.COMPRESSION_MAP for {switch}")

        compressed_block_data_size = len(block_data)

        # write the header info
        ## file size - 0 for now, will be set at the end
        writer_header_pos = writer.Position
        writer.write_long(0)
        # compressed blockInfoBytes size
        writer.write_u_int(compressed_block_data_size)
        # uncompressed size
        writer.write_u_int(uncompressed_block_data_size)
        # compression and file layout flag
        writer.write_u_int(data_flag)

        # UnityWeb version 6
        if self.signature != "UnityFS":
            writer.write_byte(0)

        if self._uses_block_alignment:
            # UnityFS\x00 - 8
            # size 8
            # comp sizes 4+4
            # flag 4
            # sum : 28 -> +8 alignment
            writer.align_stream(16)

        if data_flag & 0x80:  # at end of file
            if data_flag & 0x200:
                writer.align_stream(16)
            writer.write(file_data)
            writer.write(block_data)
        else:
            writer.write(block_data)
            if data_flag & 0x200:
                writer.align_stream(16)
            writer.write(file_data)

        writer_end_pos = writer.Position
        writer.Position = writer_header_pos
        # correct file size
        writer.write_long(writer_end_pos)
        writer.Position = writer_end_pos

    def _estimate_disk_backed_rebuild_bytes(self) -> int:
        """A rough, deliberately-not-underestimated estimate of the total
        decompressed size of the current self.files — used only for the preliminary
        free-disk-space check before save_to_file(), not for anything exact.
        For anything that provides .Length without reading (EndianBinaryReader/Writer,
        FlaggedBytesSource — including entries substituted during import) we take
        the exact length; for File objects not yet serialized (e.g. SerializedFile)
        the exact size can only be known by calling f.save() — i.e. doing the very
        expensive work this check is supposed to precede — so in that case we fall
        back to the archive's original decompressed_size as a whole (computed for
        free when the file was opened, see read_fs)."""
        total = 0
        has_unknown = False
        for f in self.files.values():
            if hasattr(f, "Length"):
                total += f.Length
            else:
                has_unknown = True
        if has_unknown:
            total = max(total, self.decompressed_size)
        return total

    def save_to_file(self, out_path, packer=None, should_cancel=None, progress_callback=None) -> None:
        """Like save(), but writes the result straight to a file on disk in a
        streaming fashion — holding neither the decompressed concatenation of the
        internal files nor the final rebuilt archive entirely in RAM (unlike save(),
        which does exactly that — see save_fs()). Intended for large archives
        (on the order of several GB+), where save() risks not fitting into available
        RAM.

        should_cancel (if given, called with no arguments, returning True means
        cancel) and progress_callback (if given, called as
        progress_callback(phase: str, current: int, total: int)) are checked/called
        BETWEEN iterations within every phase (writing entries, compressing, final
        assembly) — unlike save(), which fundamentally cannot be interrupted or
        tracked partway through (it does all its work in a handful of large calls
        with no single point to check). This is exactly why only this streaming
        version is capable of meaningful cancellation — see save_fs_to_file() below.
        On cancellation, raises CompressionHelper.RebuildCancelled and removes the
        partially-written out_path.

        The operation itself temporarily needs MORE disk space than the final
        file (see _estimate_disk_backed_rebuild_bytes and the comment inside) —
        so free space is checked before starting, and if there isn't enough, a
        clear error is raised UP FRONT, instead of a crash/corrupted file partway
        through the operation.

        Streaming support only covers the UnityFS format (current bundles,
        including every realistically large archive in this project). The legacy
        UnityWeb/UnityRaw formats — a rare case that in practice never reaches sizes
        where this matters — simply go through the regular save() and are written
        to disk as a whole."""
        out_path = os.fspath(out_path)

        if self.signature != "UnityFS":
            data = self.save(packer)
            with open(out_path, "wb") as f:
                f.write(data)
            return

        out_dir = os.path.dirname(os.path.abspath(out_path)) or "."
        estimated_uncompressed = self._estimate_disk_backed_rebuild_bytes()
        # Peak disk usage during the streaming rebuild: the temp file holding the
        # uncompressed concatenation (~= decompressed size) COEXISTS with the temp
        # file of compressed data (<= decompressed size) during the compression
        # phase; that one, in turn, coexists with the final output file (also <=
        # decompressed size) during final assembly. So the peak is roughly 2x the
        # decompressed size. We add a margin on top (1.1x) — same principle already
        # used in _extract_bundle in main.py (there it's a 5% margin, for the simpler case).
        required_bytes = int(estimated_uncompressed * 2.2) + 16 * 1024 * 1024
        free_bytes = shutil.disk_usage(out_dir).free
        if free_bytes < required_bytes:
            raise OSError(
                f"Недостаточно места на диске для потоковой пересборки архива: "
                f"требуется примерно {required_bytes / (1024**3):.2f} ГБ (временные "
                f"файлы на время операции + итоговый результат), доступно "
                f"{free_bytes / (1024**3):.2f} ГБ в «{out_dir}»."
            )

        if not packer or packer == "none":
            data_flag, block_info_flag = 64, 64
        elif packer == "original":
            data_flag, block_info_flag = self.dataflags, self._block_info_flags
        elif packer == "lz4":
            data_flag, block_info_flag = 194, 2
        elif packer == "lz4hc":
            data_flag, block_info_flag = 195, 3
        elif packer == "lzma":
            data_flag, block_info_flag = 65, 1
        elif isinstance(packer, tuple):
            data_flag, block_info_flag = packer
        else:
            raise NotImplementedError("UnityFS - Packer:", packer)

        # file_header: signature/version/version_player/version_engine — written BEFORE
        # the UnityFS body (see save(): the writer is created once and passed down
        # into save_fs()/save_fs_to_file() already containing this prefix). We open
        # the output file here and keep writing to that same writer inside
        # save_fs_to_file — not through a separate open() inside it, or the result
        # would be a file WITHOUT this prefix (exactly how this was broken the first
        # time it was implemented).
        cancelled = False
        try:
            with open(out_path, "wb") as out_f:
                writer = EndianBinaryWriter(out_f)
                writer.write_string_to_null(self.signature)
                writer.write_u_int(self.version)
                writer.write_string_to_null(self.version_player)
                writer.write_string_to_null(self.version_engine)
                self.save_fs_to_file(
                    writer, out_dir, data_flag=data_flag, block_info_flag=block_info_flag,
                    should_cancel=should_cancel, progress_callback=progress_callback,
                )
        except CompressionHelper.RebuildCancelled:
            cancelled = True
            raise
        finally:
            # better to delete a file left unfinished by a cancellation than to leave
            # a partially-written "archive" that looks like a file but won't open
            if cancelled and os.path.exists(out_path):
                try:
                    os.remove(out_path)
                except OSError:
                    pass
        clear_bundle_cache(self._cache_id)

    def save_fs_to_file(
        self,
        writer: EndianBinaryWriter,
        out_dir: str,
        data_flag: int,
        block_info_flag: int,
        should_cancel=None,
        progress_callback=None,
    ) -> None:
        """The streaming (disk-backed) equivalent of save_fs() — see save_to_file()
        for context. Takes an already-open writer (continues the same file stream
        that save_to_file() wrote signature/version into just before — the same way
        save_fs() keeps writing into the writer passed to it rather than creating
        its own).
        Uses two temp files in out_dir (the same filesystem as the final file —
        without this, the temp write itself might not fit on the system drive even
        if the target drive has enough space):
          1. TEMP_RAW — the concatenation of the uncompressed bytes of all
             self.files (replacing save_fs()'s in-memory data_writer).
          2. TEMP_COMPRESSED — the result of streaming-compressing TEMP_RAW
             (replacing CompressionHelper.chunk_based_compress() in memory).
        TEMP_RAW is deleted right after the compression phase (no longer needed),
        TEMP_COMPRESSED right after being copied into the final file. On any error,
        both temp files are cleaned up in a finally block."""
        # Both mkstemp() calls (and the raw one's cleanup-on-failure) live inside this
        # try/except rather than before it — otherwise, if the SECOND mkstemp() call
        # raised (disk full, permissions, path length), the first temp file's fd would
        # never be closed and its path never removed, leaking it permanently with no
        # code path left to revisit it.
        raw_fd = raw_path = compressed_fd = compressed_path = None
        try:
            raw_fd, raw_path = tempfile.mkstemp(prefix="unitypy_rebuild_raw_", dir=out_dir)
            compressed_fd, compressed_path = tempfile.mkstemp(prefix="unitypy_rebuild_cdata_", dir=out_dir)
        except BaseException:
            if raw_fd is not None:
                os.close(raw_fd)
                try:
                    os.remove(raw_path)
                except OSError:
                    pass
            raise
        # mkstemp() returns already-open low-level file descriptors — close them
        # right away and reopen by path via open() as needed later. Otherwise, for
        # example, compressed_fd would stay unwrapped/unclosed until phase 2, and if
        # phase 1 raises before that, os.remove(compressed_path) in finally would
        # silently fail on Windows (can't delete a file with an open handle — the
        # same category of problem already documented in CLAUDE.md regarding mmap
        # handles in environment.load_files).
        os.close(raw_fd)
        os.close(compressed_fd)
        raw_deleted = False
        try:
            # Phase 1: concatenate the contents of all internal files — to disk,
            # NOT into RAM (unlike data_writer in save_fs()).
            # Progress is tracked in BYTES across all entries combined (not by entry
            # index) — otherwise an archive with one huge entry among many small ones
            # (e.g. a large .resS) would look "stuck" for the whole time it's being
            # copied: the entry index wouldn't move until it was read in full.
            # Byte-based tracking is only possible when EVERY entry's .Length is known
            # upfront without reading its content — in practice that's the case
            # (FlaggedBytesSource/EndianBinaryWriter both provide it for free);
            # otherwise we fall back to counting by entry, as before.
            total_entries = len(self.files)
            total_write_bytes = 0
            bytes_progress_available = True
            for f in self.files.values():
                if hasattr(f, "Length"):
                    total_write_bytes += f.Length
                else:
                    bytes_progress_available = False
                    break

            report_write = CompressionHelper.ThrottledProgress(
                (lambda cur, tot: progress_callback("write", cur, tot)) if progress_callback is not None else None
            )

            files = []
            cumulative_written = 0
            with open(raw_path, "wb") as raw_out:
                for i, (name, f) in enumerate(self.files.items()):
                    if should_cancel is not None and should_cancel():
                        raise CompressionHelper.RebuildCancelled()
                    if bytes_progress_available:
                        report_write(cumulative_written, total_write_bytes)
                    else:
                        report_write(i, total_entries)

                    if hasattr(f, "write_to_stream"):
                        if bytes_progress_available:
                            # pass write_to_stream a callback that adds its OWN
                            # internal progress to the phase's running total — so one
                            # long entry moves the progress bar WITHIN itself too, not
                            # only between entries (see its docstring — the real
                            # report was "reached 99%, then 5 minutes of silence")
                            base = cumulative_written
                            length = f.write_to_stream(
                                raw_out, should_cancel=should_cancel,
                                progress_callback=lambda done, _tot, base=base: report_write(base + done, total_write_bytes),
                            )
                        else:
                            length = f.write_to_stream(raw_out, should_cancel=should_cancel)
                    else:
                        # hasattr(f, "bytes") — not a strict isinstance — so this
                        # also accepts objects like FlaggedBytesSource without
                        # write_to_stream (in case of future implementations).
                        data = f.bytes if hasattr(f, "bytes") else f.save()
                        raw_out.write(data)
                        length = len(data)

                    cumulative_written += length
                    files.append((name, f.flags, length))

            if bytes_progress_available:
                report_write(total_write_bytes, total_write_bytes, force=True)
            else:
                report_write(total_entries, total_entries, force=True)
            total_uncompressed = sum(f_len for _, _, f_len in files)

            # remove encryption flag, as encryption isn't done (same as in save_fs())
            if block_info_flag & self.dataflags.UsesAssetBundleEncryption:
                block_info_flag ^= self.dataflags.UsesAssetBundleEncryption
            if data_flag & self.dataflags.UsesAssetBundleEncryption:
                data_flag ^= self.dataflags.UsesAssetBundleEncryption

            # Phase 2: stream-compress TEMP_RAW -> TEMP_COMPRESSED (replaces
            # CompressionHelper.chunk_based_compress(file_data, block_info_flag)).
            # Usually the longest phase — and it has the most frequent cancellation
            # checkpoint (by compression chunk — 128KB for LZ4/LZ4HC, up to 8MB reads
            # for LZMA; see chunk_based_compress_stream()).
            with open(raw_path, "rb") as raw_in, open(compressed_path, "wb") as compressed_out:
                block_info = CompressionHelper.chunk_based_compress_stream(
                    raw_in, total_uncompressed, block_info_flag, compressed_out,
                    should_cancel=should_cancel,
                    progress_callback=(
                        (lambda cur, tot: progress_callback("compress", cur, tot))
                        if progress_callback is not None else None
                    ),
                    tmp_dir=out_dir,
                )
            compressed_file_data_size = os.path.getsize(compressed_path)

            # TEMP_RAW is no longer needed — free up disk space before final assembly
            os.remove(raw_path)
            raw_deleted = True

            # Phase 3: the metadata block (blockinfo + directory) — small,
            # proportional to the number of blocks/files, not to the data volume; as
            # in save_fs(), it's built and compressed in memory with no real risk.
            block_writer = EndianBinaryWriter(b"\x00" * 0x10)
            block_writer.write_int(len(block_info))
            for block_uncompressed_size, block_compressed_size, block_flag in block_info:
                block_writer.write_u_int(block_uncompressed_size)
                block_writer.write_u_int(block_compressed_size)
                block_writer.write_u_short(block_flag)

            if not data_flag & 0x40:
                raise NotImplementedError("UnityPy always writes DirectoryInfo, so data_flag must include 0x40")
            block_writer.write_int(len(files))
            offset = 0
            for f_name, f_flag, f_len in files:
                block_writer.write_long(offset)
                block_writer.write_long(f_len)
                offset += f_len
                block_writer.write_u_int(f_flag)
                block_writer.write_string_to_null(f_name)

            block_data = block_writer.bytes
            block_writer.dispose()
            uncompressed_block_data_size = len(block_data)

            switch = data_flag & 0x3F
            if switch in CompressionHelper.COMPRESSION_MAP:
                block_data = CompressionHelper.COMPRESSION_MAP[switch](block_data)
            else:
                raise NotImplementedError(f"No compression function in the CompressionHelper.COMPRESSION_MAP for {switch}")
            compressed_block_data_size = len(block_data)

            # Phase 4: append to the SAME writer already obtained from the calling
            # save_to_file() (it already holds the signature/version prefix) — the
            # block/blockinfo header is written by the same code as in save_fs(), and
            # the compressed block data is copied in from TEMP_COMPRESSED in chunks,
            # not with one big writer.write(file_data) call.
            writer_header_pos = writer.Position
            writer.write_long(0)
            writer.write_u_int(compressed_block_data_size)
            writer.write_u_int(uncompressed_block_data_size)
            writer.write_u_int(data_flag)

            if self.signature != "UnityFS":
                writer.write_byte(0)

            if self._uses_block_alignment:
                writer.align_stream(16)

            def _copy_compressed_data_blocks():
                copied = 0
                with open(compressed_path, "rb") as src:
                    while True:
                        if should_cancel is not None and should_cancel():
                            raise CompressionHelper.RebuildCancelled()
                        chunk = src.read(8 * 1024 * 1024)
                        if not chunk:
                            break
                        writer.write(chunk)
                        copied += len(chunk)
                        if progress_callback is not None:
                            progress_callback("assemble", copied, compressed_file_data_size)

            if data_flag & 0x80:  # at end of file
                if data_flag & 0x200:
                    writer.align_stream(16)
                _copy_compressed_data_blocks()
                writer.write(block_data)
            else:
                writer.write(block_data)
                if data_flag & 0x200:
                    writer.align_stream(16)
                _copy_compressed_data_blocks()

            writer_end_pos = writer.Position
            writer.Position = writer_header_pos
            writer.write_long(writer_end_pos)
            writer.Position = writer_end_pos
        finally:
            if not raw_deleted and os.path.exists(raw_path):
                try:
                    os.remove(raw_path)
                except OSError:
                    pass
            if os.path.exists(compressed_path):
                try:
                    os.remove(compressed_path)
                except OSError:
                    pass

    def save_web_raw(self, writer: EndianBinaryWriter):
        # (version >= 4) hash
        # (version >= 4) crc
        # minimumStreamedBytes
        # headerSize
        # numberOfLevelsToDownloadBeforeStreaming
        # levelCount
        # compressedSize * levelCount
        # uncompressedSize * levelCount
        # (version >= 2) completeFileSize
        # (version >= 3) file_info_header_size
        # compressed assets

        if self.version > 3:
            raise NotImplementedError("Saving Unity Web bundles with version > 3 is not supported")

        # Calculate fileInfoHeaderSize for set offsets
        file_info_header_size = 4  # for nodesCount

        for file_name in self.files.keys():
            file_info_header_size += len(file_name.encode()) + 1  # +1 for null terminator
            file_info_header_size += 4 * 2  # 4 bytes each for offset and size

        file_info_header_padding_size = 4 - (file_info_header_size % 4) if file_info_header_size % 4 != 0 else 0
        file_info_header_size += file_info_header_padding_size

        # Prepare directory info
        directory_info_writer = EndianBinaryWriter()
        directory_info_writer.write_int(len(self.files))  # nodesCount

        file_content_writer = EndianBinaryWriter()
        current_offset = file_info_header_size

        for file_name, f in self.files.items():
            directory_info_writer.write_string_to_null(file_name)
            directory_info_writer.write_u_int(current_offset)

            # Get file content. hasattr(f, "bytes") rather than the old strict
            # isinstance check — same reasoning as save_fs()/save_fs_to_file() above:
            # it also picks up a SerializedFile's own `bytes` property (an
            # object_count_only stub's raw passthrough) without which this path
            # would call f.save() on an unparsed stub and crash/corrupt it exactly
            # like save_fs() used to.
            if hasattr(f, "bytes"):
                file_data = f.bytes
            else:
                file_data = f.save()

            file_size = len(file_data)
            directory_info_writer.write_u_int(file_size)

            file_content_writer.write_bytes(file_data)
            current_offset += file_size

        directory_info_writer.write(b"\x00" * file_info_header_padding_size)
        uncompressed_directory_info = directory_info_writer.bytes
        uncompressed_file_content = file_content_writer.bytes

        # Combine directory info and file content
        uncompressed_content = uncompressed_directory_info + uncompressed_file_content
        compressed_content = uncompressed_content
        if self.signature == "UnityWeb":
            compressed_content = CompressionHelper.compress_lzma(uncompressed_content, True)

        # Write header
        header_size = writer.Position + 24  # assuming levelCount = 1
        if self.version >= 2:
            header_size += 4
        if self.version >= 3:
            header_size += 4
        if self.version >= 4:
            header_size += 20
        # pad to multiple of 4
        header_size = (header_size + 3) & ~3

        if self.version >= 4:
            writer.write_bytes(self._hash)
            writer.write_u_int(self.crc)

        writer.write_u_int(header_size + len(compressed_content))  # minimumStreamedBytes (same as completeFileSize)
        writer.write_u_int(header_size)  # headerSize
        writer.write_u_int(1)  # numberOfLevelsToDownloadBeforeStreaming (always 1)
        writer.write_int(1)  # levelCount (always 1)

        writer.write_u_int(len(compressed_content))  # compressedSize
        writer.write_u_int(len(uncompressed_content))  # uncompressedSize

        if self.version >= 2:
            writer.write_u_int(header_size + len(compressed_content))  # completeFileSize

        if self.version >= 3:
            writer.write_u_int(file_info_header_size)  # file_info_header_size

        # align header
        writer.align_stream(4)

        # Write compressed content
        writer.write(compressed_content)

    def decompress_data(
        self,
        compressed_data: bytes,
        uncompressed_size: int,
        flags: Union[int, ArchiveFlags, ArchiveFlagsOld],
        index: int = 0,
    ) -> bytes:
        """
        Parameters
        ----------
        compressed_data : bytes
            The compressed data.
        uncompressed_size : int
            The uncompressed size of the data.
        flags : int
            The flags of the data.

        Returns
        -------
        bytes
            The decompressed data."""
        comp_flag = CompressionFlags(flags & ArchiveFlags.CompressionTypeMask)

        if self.decryptor is not None and flags & 0x100 and comp_flag != CompressionFlags.NONE:
            compressed_data = self.decryptor.decrypt_block(compressed_data, index)

        if comp_flag in CompressionHelper.DECOMPRESSION_MAP:
            return cast(
                bytes,
                CompressionHelper.DECOMPRESSION_MAP[comp_flag](compressed_data, uncompressed_size),
            )
        else:
            raise ValueError(f"Unknown compression! flag: {flags}, compression flag: {comp_flag.value}")

    def parse_version(self) -> UnityVersion:
        """Returns the version as a tuple."""
        version = None
        version_str = self.version_engine
        try:
            version = UnityVersion.from_str(version_str)
        except ValueError:
            pass

        if version is None or version.major == 0:
            version_str = config.get_fallback_version()
            version = UnityVersion.from_str(version_str)

        return version
