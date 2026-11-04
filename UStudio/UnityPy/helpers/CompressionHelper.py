import gzip
import lzma
import os
import struct
import tempfile
import time
from typing import Callable, Dict, Tuple, Union

import brotli
import lz4.block

from ..enums.BundleFile import CompressionFlags

ByteString = Union[bytes, bytearray, memoryview]
GZIP_MAGIC: bytes = b"\x1f\x8b"
BROTLI_MAGIC: bytes = b"brotli"


# LZMA
def decompress_lzma(data: ByteString, read_decompressed_size: bool = False) -> bytes:
    """decompresses lzma-compressed data

    :param data: compressed data
    :type data: ByteString
    :raises _lzma.LZMAError: Compressed data ended before the end-of-stream marker was reached
    :return: uncompressed data
    :rtype: bytes
    """
    props, dict_size = struct.unpack("<BI", data[:5])
    lc = props % 9
    remainder = props // 9
    pb = remainder // 5
    lp = remainder % 5
    dec = lzma.LZMADecompressor(
        format=lzma.FORMAT_RAW,
        filters=[
            {
                "id": lzma.FILTER_LZMA1,
                "dict_size": dict_size,
                "lc": lc,
                "lp": lp,
                "pb": pb,
            }
        ],
    )
    data_offset = 13 if read_decompressed_size else 5
    return dec.decompress(data[data_offset:])


def compress_lzma(data: ByteString, write_decompressed_size: bool = False) -> bytes:
    """compresses data via lzma (unity specific)
    The current static settings may not be the best solution,
    but they are the most commonly used values and should therefore be enough for the time being.

    :param data: uncompressed data
    :type data: ByteString
    :return: compressed data
    :rtype: bytes
    """
    dict_size = 0x800000  # 1 << 23
    compressor = lzma.LZMACompressor(
        format=lzma.FORMAT_RAW,
        filters=[
            {
                "id": lzma.FILTER_LZMA1,
                "dict_size": dict_size,
                "lc": 3,
                "lp": 0,
                "pb": 2,
                "mode": lzma.MODE_NORMAL,
                "mf": lzma.MF_BT4,
                "nice_len": 123,
            }
        ],
    )

    compressed_data = compressor.compress(data) + compressor.flush()
    cdl = len(compressed_data)
    if write_decompressed_size:
        return struct.pack(f"<BIQ{cdl}s", 0x5D, dict_size, len(data), compressed_data)
    else:
        return struct.pack(f"<BI{cdl}s", 0x5D, dict_size, compressed_data)


# LZ4
def decompress_lz4(data: ByteString, uncompressed_size: int) -> bytes:  # LZ4M/LZ4HC
    """decompresses lz4-compressed data

    :param data: compressed data
    :type data: ByteString
    :param uncompressed_size: size of the uncompressed data
    :type uncompressed_size: int
    :raises _block.LZ4BlockError: Decompression failed: corrupt input or insufficient space in destination buffer.
    :return: uncompressed data
    :rtype: bytes
    """
    return lz4.block.decompress(data, uncompressed_size)


def compress_lz4(data: ByteString) -> bytes:  # LZ4M/LZ4HC
    """compresses data via lz4.block

    :param data: uncompressed data
    :type data: ByteString
    :return: compressed data
    :rtype: bytes
    """
    return lz4.block.compress(data, mode="high_compression", compression=9, store_size=False)


# Brotli
def decompress_brotli(data: ByteString) -> bytes:
    """decompresses brotli-compressed data

    :param data: compressed data
    :type data: ByteString
    :raises brotli.error: BrotliDecompress failed
    :return: uncompressed data
    :rtype: bytes
    """
    return brotli.decompress(data)


def compress_brotli(data: ByteString) -> bytes:
    """compresses data via brotli

    :param data: uncompressed data
    :type data: ByteString
    :return: compressed data
    :rtype: bytes
    """
    return brotli.compress(data)


# GZIP
def decompress_gzip(data: ByteString) -> bytes:
    """decompresses gzip-compressed data

    :param data: compressed data
    :type data: ByteString
    :raises OSError: Not a gzipped file
    :return: uncompressed data
    :rtype: bytes
    """
    return gzip.decompress(data)


def compress_gzip(data: ByteString) -> bytes:
    """compresses data via gzip
    The current static settings may not be the best solution,
    but they are the most commonly used values and should therefore be enough for the time being.

    :param data: uncompressed data
    :type data: ByteString
    :return: compressed data
    :rtype: bytes
    """
    return gzip.compress(data)


def chunk_based_compress(data: ByteString, block_info_flag: int) -> Tuple[ByteString, list]:
    """compresses AssetBundle data based on the block_info_flag
    LZ4/LZ4HC will be chunk-based compression

    :param data: uncompressed data
    :type data: ByteString
    :param block_info_flag: block info flag
    :type block_info_flag: int
    :return: compressed data and block info
    :rtype: tuple
    """
    switch = block_info_flag & 0x3F
    chunk_size = None
    compress_func = None
    # NONE (switch == 0) used to be special-cased here as one early-returned block
    # covering the WHOLE input regardless of size — wrong for any input over
    # ~4GB, since block_uncompressed_size/block_compressed_size are written as
    # unsigned 32-bit fields (struct format 'I', max 4294967295) in the archive's
    # block-info table (see BundleFile.py's save_fs()/save_fs_to_file()); a single
    # oversized NONE block crashes with "'I' format requires 0 <= number <=
    # 4294967295" the moment it's written out. COMPRESSION_MAP[NONE] (identity)
    # and COMPRESSION_CHUNK_SIZE_MAP[NONE] (0xFFFFFFFF) already exist specifically
    # so NONE falls through the same chunking loop below as every other
    # compression type — no special case needed, it was just wired to bypass it.

    if switch in COMPRESSION_MAP:
        compress_func = COMPRESSION_MAP[switch]
    else:
        raise NotImplementedError(f"No compression function in the CompressionHelper.COMPRESSION_MAP for {switch}")

    if switch in COMPRESSION_CHUNK_SIZE_MAP:
        chunk_size = COMPRESSION_CHUNK_SIZE_MAP[switch]
    else:
        raise NotImplementedError(f"No chunk size in the CompressionHelper.COMPRESSION_CHUNK_SIZE_MAP for {switch}")

    block_info = []
    uncompressed_data_size = len(data)
    compressed_file_data = bytearray()
    p = 0
    while uncompressed_data_size >= chunk_size:
        compressed_data = compress_func(data[p : p + chunk_size])
        if len(compressed_data) >= chunk_size:
            compressed_file_data.extend(data[p : p + chunk_size])
            block_info.append(
                (
                    chunk_size,
                    chunk_size,
                    block_info_flag ^ switch,
                )
            )
        else:
            compressed_file_data.extend(compressed_data)
            block_info.append(
                (
                    chunk_size,
                    len(compressed_data),
                    block_info_flag,
                )
            )
        p += chunk_size
        uncompressed_data_size -= chunk_size
    if uncompressed_data_size > 0:
        compressed_data = compress_func(data[p:])
        if len(compressed_data) > uncompressed_data_size:
            compressed_file_data.extend(data[p:])
            block_info.append(
                (
                    uncompressed_data_size,
                    uncompressed_data_size,
                    block_info_flag ^ switch,
                )
            )
        else:
            compressed_file_data.extend(compressed_data)
            block_info.append(
                (
                    uncompressed_data_size,
                    len(compressed_data),
                    block_info_flag,
                )
            )
    return bytes(compressed_file_data), block_info


class RebuildCancelled(Exception):
    """Raised by chunk_based_compress_stream()/compress_lzma_stream() (and,
    further up, BundleFile.save_to_file()/save_fs_to_file()) when the given
    should_cancel() returns True. Checked between iterations (per compression/
    read chunk), not just once before/after the whole operation — this is
    exactly what the "soft" cancellation via QThread.requestInterruption() was
    missing in the first implementation of the disk-backed rebuild: nothing
    checked the flag inside the compression/copy itself, so cancellation only
    took effect once the background thread had ALREADY finished the work anyway."""
    pass


class ThrottledProgress:
    """Wraps progress_callback(current, total) so it's called at most once
    per min_interval seconds (plus always on completion — force=True). Needed
    because compression chunks are small (0x20000 = 128KB for LZ4/LZ4HC) — for
    a 35GB archive that's ~280,000 chunks, and calling progress_callback on EVERY
    one of them (which typically also means delivering a Qt signal to the GUI
    thread + a widget repaint) floods the GUI thread's event queue badly enough
    that the interface appears frozen, even though the real work keeps running
    in the background. The same class of problem as the time.sleep()/
    progress_signal.emit() cadence issue in this project's other background
    loops (see CLAUDE.md, the lesson about throttling by time, not by iteration
    count) — hit again here during the first implementation of the streaming
    rebuild, because compression chunks (128KB) are a much finer granularity
    than the progress points anywhere else in the project (there — hundreds/
    thousands of objects between calls, not hundreds of thousands of chunks)."""

    __slots__ = ("_callback", "_min_interval", "_last_time")

    def __init__(self, callback, min_interval: float = 0.15):
        self._callback = callback
        self._min_interval = min_interval
        self._last_time = 0.0

    def __call__(self, current: int, total: int, force: bool = False) -> None:
        if self._callback is None:
            return
        now = time.monotonic()
        if force or current >= total or now - self._last_time >= self._min_interval:
            self._last_time = now
            self._callback(current, total)


def chunk_based_compress_stream(
    read_stream,
    total_size: int,
    block_info_flag: int,
    write_stream,
    read_chunk_size: int = 8 * 1024 * 1024,
    should_cancel=None,
    progress_callback=None,
    tmp_dir: "str | None" = None,
) -> list:
    """The streaming equivalent of chunk_based_compress(): reads uncompressed
    data from read_stream in pieces (read_chunk_size — a read size chosen to
    bound memory use, NOT related to Unity's own block format), compresses and
    immediately writes the result to write_stream, never holding either the
    source or the compressed data entirely in memory.
    Returns a block_info list in the same format as chunk_based_compress().
    For NONE/LZ4/LZ4HC the result is byte-for-byte identical to
    chunk_based_compress() (same chunk boundaries, same single compression call
    per chunk). For LZMA the compressed bytes MAY differ from a single call to
    compress_lzma(data) on the whole thing — LZMA is adaptive, and how the data
    is fed to it in pieces affects the exact encoded bytes — but the decompressed
    result is always correct and matches the original data (see the LZMA branch
    below for details). Needed for BundleFile.save_to_file() — rebuilding a
    large archive without holding the entire decompressed/compressed content in
    RAM (see CLAUDE.md, the disk-backed rebuild section).

    should_cancel (if given) is checked on EVERY chunk — a cheap flag check
    that doesn't add overhead even across hundreds of thousands of chunks.
    progress_callback (if given) is called at most once per ~150ms — see
    ThrottledProgress above — with (bytes_processed, total_size).
    tmp_dir — directory for the LZMA branch's own scratch temp file (see below);
    should be the same drive as the final output, same reasoning as
    BundleFile.save_fs_to_file()'s own temp files. Defaults to the system temp
    drive when not given, matching the previous (pre-fix) behavior."""
    switch = block_info_flag & 0x3F
    report = ThrottledProgress(progress_callback)

    if switch == 0:  # NONE — just copy as-is, but still chunked (see below)
        # Same bug as chunk_based_compress()'s old NONE early-return (see its
        # comment): one block covering the ENTIRE stream overflows the 32-bit
        # block_uncompressed_size/block_compressed_size fields once total_size
        # exceeds 0xFFFFFFFF (~4GB) — crashes with "'I' format requires 0 <=
        # number <= 4294967295" when BundleFile.py writes the block-info table.
        # Chunked into COMPRESSION_CHUNK_SIZE_MAP[NONE] (0xFFFFFFFF)-sized blocks
        # instead — for total_size <= that (the overwhelmingly common case) this
        # produces exactly the same single block as before, byte-for-byte.
        chunk_size = COMPRESSION_CHUNK_SIZE_MAP[CompressionFlags.NONE]
        block_info = []
        total_copied = 0
        remaining_total = total_size
        while remaining_total > 0:
            block_size = min(chunk_size, remaining_total)
            remaining_in_block = block_size
            while remaining_in_block > 0:
                if should_cancel is not None and should_cancel():
                    raise RebuildCancelled()
                chunk = read_stream.read(min(read_chunk_size, remaining_in_block))
                if not chunk:
                    remaining_in_block = 0
                    break
                write_stream.write(chunk)
                remaining_in_block -= len(chunk)
                total_copied += len(chunk)
                report(total_copied, total_size)
            block_info.append((block_size, block_size, block_info_flag))
            remaining_total -= block_size
        report(total_size, total_size, force=True)
        return block_info

    if switch not in COMPRESSION_MAP:
        raise NotImplementedError(f"No compression function in the CompressionHelper.COMPRESSION_MAP for {switch}")
    if switch not in COMPRESSION_CHUNK_SIZE_MAP:
        raise NotImplementedError(f"No chunk size in the CompressionHelper.COMPRESSION_CHUNK_SIZE_MAP for {switch}")

    compress_func = COMPRESSION_MAP[switch]
    chunk_size = COMPRESSION_CHUNK_SIZE_MAP[switch]

    if switch == CompressionFlags.LZMA:
        # chunk_size for LZMA in COMPRESSION_CHUNK_SIZE_MAP is 0xFFFFFFFF (~4GB),
        # NOT "always one block": in the original chunk_based_compress(), the
        # "while uncompressed_data_size >= chunk_size" loop still cuts data into
        # 0xFFFFFFFF-byte pieces if the total exceeds ~4GB, and each such piece is
        # compressed with LZMA independently (with its own 5-byte header/dictionary reset).
        # Real archives in this project never reach that size in ONE LZMA block
        # (see CLAUDE.md: the only oversized fixture found was LZ4-compressed, not
        # LZMA) — so only the common, verifiable case of total_size <= 0xFFFFFFFF
        # (the whole archive as one LZMA stream) is deliberately supported here.
        # The rare "LZMA and >4GB" case would require implementing multi-block
        # splitting blind, with no reference file to check against — instead we
        # fail loudly and explicitly rather than guess (see CLAUDE.md, debugging
        # methodology: "don't write skip/offset logic for a binary format without a
        # reference implementation"). In that case the caller should use the
        # regular BundleFile.save() (whole archive in RAM).
        # (>=, not >: since upstream 1.25.4 chunk_based_compress() treats a total of
        # exactly chunk_size as a full chunk with its own ">= chunk_size -> store raw"
        # fallback, which the single-stream path below does not replicate.)
        if total_size >= 0xFFFFFFFF:
            raise NotImplementedError(
                "Потоковая пересборка не поддерживает LZMA-сжатие для архивов "
                "суммарным разжатым размером свыше ~4ГБ одним блоком (редкий случай, "
                "не встречавшийся в реальных фикстурах проекта) — используйте "
                "BundleFile.save() (в память) для этого архива."
            )

        # IMPORTANT: LZMA is an adaptive compressor, so a stream fed in pieces (to
        # limit memory use) is NOT guaranteed to produce byte-identical compressed
        # output to one call of compress_func(data) on the whole thing (where the
        # compress() call boundaries fall affects the compressor's decisions) — the
        # decompressed result, though, is always correct. That means we can't know
        # ahead of time — before compression finishes — whether the result will end
        # up SMALLER than the source data (which is exactly what the original
        # chunk_based_compress() silently checks before deciding whether to store it
        # compressed or as-is). So we first compress into a TEMP FILE (not memory —
        # the exact same reasoning this whole function exists for), then compare the
        # size and copy into write_stream either the compressed result or (a rare
        # fallback, same as the original) the source bytes as-is — which requires
        # read_stream to support seek() back to the start.
        start_pos = read_stream.tell()
        tmp_fd, tmp_path = tempfile.mkstemp(prefix="unitypy_lzma_stream_", dir=tmp_dir)
        try:
            with os.fdopen(tmp_fd, "wb") as tmp_out:
                compressed_size = compress_lzma_stream(
                    read_stream, total_size, tmp_out,
                    should_cancel=should_cancel, progress_callback=progress_callback,
                )

            # original chunk_based_compress() falls back to raw storage only when
            # compressed is STRICTLY LARGER than the source (`>`) — an equal-size
            # result is kept compressed. <= here (not <) matches that boundary exactly.
            if compressed_size <= total_size:
                with open(tmp_path, "rb") as tmp_in:
                    while True:
                        if should_cancel is not None and should_cancel():
                            raise RebuildCancelled()
                        chunk = tmp_in.read(read_chunk_size)
                        if not chunk:
                            break
                        write_stream.write(chunk)
                return [(total_size, compressed_size, block_info_flag)]
            else:
                # fallback: compression didn't help (or there wasn't enough data) —
                # copy the source bytes as-is, with the "uncompressed" flag —
                # same behavior as chunk_based_compress() in this case.
                read_stream.seek(start_pos)
                remaining = total_size
                while remaining > 0:
                    if should_cancel is not None and should_cancel():
                        raise RebuildCancelled()
                    chunk = read_stream.read(min(read_chunk_size, remaining))
                    if not chunk:
                        break
                    write_stream.write(chunk)
                    remaining -= len(chunk)
                return [(total_size, total_size, block_info_flag ^ switch)]
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    # Chunked mode (LZ4/LZ4HC) — read and compress in exactly the same size chunks
    # as chunk_based_compress(), including the same "store as-is" fallback if the
    # compressed chunk isn't smaller than the source. Chunks are small (0x20000 =
    # 128KB), so checking should_cancel() on every iteration is a frequent, responsive
    # cancellation point.
    block_info = []
    remaining = total_size
    processed = 0
    # `>=` / `>= chunk_size` mirror chunk_based_compress() as of upstream 1.25.4
    # (e35a18a) — keep the two in lockstep so their output stays byte-identical.
    while remaining >= chunk_size:
        if should_cancel is not None and should_cancel():
            raise RebuildCancelled()
        chunk = read_stream.read(chunk_size)
        if len(chunk) != chunk_size:
            raise IOError(f"Unexpected end of stream while reading a compression chunk (expected {chunk_size}, got {len(chunk)})")
        compressed_data = compress_func(chunk)
        if len(compressed_data) >= chunk_size:
            write_stream.write(chunk)
            block_info.append((chunk_size, chunk_size, block_info_flag ^ switch))
        else:
            write_stream.write(compressed_data)
            block_info.append((chunk_size, len(compressed_data), block_info_flag))
        remaining -= chunk_size
        processed += chunk_size
        report(processed, total_size)

    if remaining > 0:
        if should_cancel is not None and should_cancel():
            raise RebuildCancelled()
        chunk = read_stream.read(remaining)
        if len(chunk) != remaining:
            raise IOError(f"Unexpected end of stream while reading the final compression chunk (expected {remaining}, got {len(chunk)})")
        compressed_data = compress_func(chunk)
        if len(compressed_data) > remaining:
            write_stream.write(chunk)
            block_info.append((remaining, remaining, block_info_flag ^ switch))
        else:
            write_stream.write(compressed_data)
            block_info.append((remaining, len(compressed_data), block_info_flag))

    report(total_size, total_size, force=True)
    return block_info


def compress_lzma_stream(
    read_stream,
    total_size: int,
    write_stream,
    read_chunk_size: int = 8 * 1024 * 1024,
    should_cancel=None,
    progress_callback=None,
) -> int:
    """The streaming equivalent of compress_lzma(data, write_decompressed_size=False)
    — the same output format (1 properties byte + 4-byte dict_size + compressed
    data), byte-for-byte identical result, but the data is read/compressed/
    written in pieces instead of one large call. Returns the total size of the
    compressed bytes written (including the header). should_cancel/
    progress_callback — see the chunk_based_compress_stream() docstring above."""
    dict_size = 0x800000  # 1 << 23 — same settings as in compress_lzma()
    compressor = lzma.LZMACompressor(
        format=lzma.FORMAT_RAW,
        filters=[
            {
                "id": lzma.FILTER_LZMA1,
                "dict_size": dict_size,
                "lc": 3,
                "lp": 0,
                "pb": 2,
                "mode": lzma.MODE_NORMAL,
                "mf": lzma.MF_BT4,
                "nice_len": 123,
            }
        ],
    )

    header = struct.pack("<BI", 0x5D, dict_size)
    write_stream.write(header)
    written = len(header)

    report = ThrottledProgress(progress_callback)
    remaining = total_size
    processed = 0
    while remaining > 0:
        if should_cancel is not None and should_cancel():
            raise RebuildCancelled()
        chunk = read_stream.read(min(read_chunk_size, remaining))
        if not chunk:
            break
        remaining -= len(chunk)
        processed += len(chunk)
        out = compressor.compress(chunk)
        if out:
            write_stream.write(out)
            written += len(out)
        report(processed, total_size)

    tail = compressor.flush()
    if tail:
        write_stream.write(tail)
        written += len(tail)

    report(total_size, total_size, force=True)

    return written


def decompress_lzham(data: ByteString, uncompressed_size: int) -> bytes:
    raise NotImplementedError("Custom compression or unimplemented LZHAM (removed by Unity) encountered!")


DECOMPRESSION_MAP: Dict[Union[int, CompressionFlags], Callable[[ByteString, int], ByteString]] = {
    CompressionFlags.NONE: lambda cd, _ucs: cd,
    CompressionFlags.LZMA: lambda cd, _ucs: decompress_lzma(cd),
    CompressionFlags.LZ4: decompress_lz4,
    CompressionFlags.LZ4HC: decompress_lz4,
    CompressionFlags.LZHAM: decompress_lzham,
}

COMPRESSION_MAP: Dict[Union[int, CompressionFlags], Callable[[ByteString], ByteString]] = {
    CompressionFlags.NONE: lambda cd: cd,
    CompressionFlags.LZMA: compress_lzma,
    CompressionFlags.LZ4: compress_lz4,
    CompressionFlags.LZ4HC: compress_lz4,
}

COMPRESSION_CHUNK_SIZE_MAP: Dict[Union[int, CompressionFlags], int] = {
    CompressionFlags.NONE: 0xFFFFFFFF,
    CompressionFlags.LZMA: 0xFFFFFFFF,
    CompressionFlags.LZ4: 0x00020000,
    CompressionFlags.LZ4HC: 0x00020000,
}


__all__ = (
    "compress_brotli",
    "compress_gzip",
    "compress_lz4",
    "compress_lzma",
    "decompress_brotli",
    "decompress_gzip",
    "decompress_lz4",
    "decompress_lzma",
    "decompress_lzham",
    "chunk_based_compress",
    "chunk_based_compress_stream",
    "compress_lzma_stream",
    "RebuildCancelled",
    "ThrottledProgress",
    "COMPRESSION_MAP",
    "DECOMPRESSION_MAP",
    "COMPRESSION_CHUNK_SIZE_MAP",
)
