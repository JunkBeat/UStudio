from __future__ import annotations

import io
import logging
import mmap
import os
from gzip import GzipFile
from typing import BinaryIO, List, Optional, Tuple, Union

from .. import files
from ..enums import FileType
from ..streams import EndianBinaryReader
from .CompressionHelper import BROTLI_MAGIC, GZIP_MAGIC

logger = logging.getLogger("UnityPy.helpers.ImportHelper")

FileSourceType = Union[str, bytes, bytearray, io.IOBase, EndianBinaryReader, BinaryIO]


def file_name_without_extension(file_name: str) -> str:
    return os.path.join(os.path.dirname(file_name), os.path.splitext(os.path.basename(file_name))[0])


def list_all_files(directory: str) -> List[str]:
    # Sorted so callers that resolve ties by list order (e.g. cab_collision_policy
    # "keep_first"/"keep_last") get a stable, explicable result instead of whatever
    # order os.walk()'s underlying directory-enumeration API happens to return.
    return sorted(
        val
        for sublist in [
            [os.path.join(dir_path, filename) for filename in filenames]
            for (dir_path, dirnames, filenames) in os.walk(directory)
            if ".git" not in dir_path
        ]
        for val in sublist
    )


def find_all_files(directory: str, search_str: str) -> List[str]:
    return sorted(
        val
        for sublist in [
            [os.path.join(dir_path, filename) for filename in filenames if search_str in filename]
            for (dir_path, dirnames, filenames) in os.walk(directory)
            if ".git" not in dir_path
        ]
        for val in sublist
    )


def check_file_type(
    input_: FileSourceType,
) -> Tuple[FileType, EndianBinaryReader]:
    if isinstance(input_, str) and os.path.isfile(input_):
        with open(input_, "rb") as f:
            try:
                mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            except (OSError, ValueError):
                reader = EndianBinaryReader(open(input_, "rb"))
            else:
                reader = EndianBinaryReader(memoryview(mm))
    elif isinstance(input_, EndianBinaryReader):
        reader = input_
    else:
        reader = EndianBinaryReader(input_)

    # Must be <= (not <): read_string_to_null(20) below gives up and raises
    # "String not terminated" once Position + max_length >= Length, i.e. once
    # Length <= 20 (Position is 0 here) — a file of EXACTLY 20 bytes with no
    # null byte anywhere (a short plain-text file, common under StreamingAssets:
    # confirmed via two real, unrelated games — Length < 20 skipped this guard
    # by exactly one byte, letting a completely ordinary non-Unity file crash
    # the whole check instead of falling back to ResourceFile like every other
    # too-small-to-be-a-real-header file already does.
    if reader.Length <= 20:
        return FileType.ResourceFile, reader

    signature = reader.read_string_to_null(20)

    reader.Position = 0
    if signature in [
        "UnityWeb",
        "UnityRaw",
        "\xfa\xfa\xfa\xfa\xfa\xfa\xfa\xfa",
        "UnityFS",
    ]:
        return FileType.BundleFile, reader
    elif signature.startswith(("UnityWebData", "TuanjieWebData")):
        return FileType.WebFile, reader
    elif signature == "PK\x03\x04":
        return FileType.ZIP, reader
    else:
        if reader.Length < 128:
            return FileType.ResourceFile, reader

        magic = bytes(reader.read_bytes(2))
        reader.Position = 0
        if GZIP_MAGIC == magic:
            g_stream = GzipFile(fileobj=reader)
            g_reader = EndianBinaryReader(g_stream, endian="<")
            signature = g_reader.read_string_to_null(20)
            g_stream.close()
            if signature.startswith(("UnityWebData", "TuanjieWebData")):
                return FileType.WebFile, reader
        reader.Position = 0x20
        magic = bytes(reader.read_bytes(6))
        reader.Position = 0
        if BROTLI_MAGIC == magic:
            return FileType.WebFile, reader

        # check if AssetsFile
        old_endian = reader.endian
        # read as if assetsfile and check version
        # ReadHeader
        reader.Position = 0
        metadata_size = reader.read_u_int()
        file_size = reader.read_u_int()
        version = reader.read_u_int()
        data_offset = reader.read_u_int()

        if version >= 22:
            raw_endian = reader.read_u_byte()
            _endian = ">" if raw_endian else "<"
            _reserved = reader.read_bytes(3)
            metadata_size = reader.read_u_int()
            file_size = reader.read_long()
            data_offset = reader.read_long()
            _unknown = reader.read_long()  # unknown

        # reset
        reader.endian = old_endian
        reader.Position = 0
        # check info
        if any(
            (
                # Real SerializedFile format versions have always been >= 5 for
                # anything this codebase's own version-branching logic (see
                # files/SerializedFile.py) treats as a distinct case, and every
                # real fixture checked (multiple games, version 22) confirms this —
                # version 0 is not a real value, just what four arbitrary bytes of
                # non-Unity binary data happen to decode to. Without this, an
                # ordinary non-asset .bytes file (confirmed via a real shipped
                # game: Unity's own baked Adaptive Probe Volume data under
                # StreamingAssets/APVStreamingAssets/, which is raw float/int
                # data, not a serialized asset) can have its first 16 bytes
                # coincidentally look like a small, "plausible" SerializedFile
                # header (metadata_size=0, file_size=56, version=0, data_offset=56
                # for the confirmed case) and pass every other check here,
                # misclassifying it as FileType.AssetsFile. SerializedFile then
                # tries to parse the rest of the file as real TypeTree metadata —
                # for genuinely random bytes this can make TypeTreeNode.parse()'s
                # recursive tree-building (unbounded, no sanity limits — see the
                # "not yet reviewed" note on parse_blob) run for a very long time
                # while memory climbs, which is what this was actually causing:
                # not a crash, an effectively-unbounded parse of garbage as if it
                # were a deeply nested type tree. This check doesn't make
                # TypeTreeNode.parse() itself safe against a still-plausible-enough
                # garbage header — it only closes the one concrete case found.
                version < 1,
                version > 100,
                *[x < 0 or x > reader.Length for x in [file_size, metadata_size, version, data_offset]],
                file_size < metadata_size,
                file_size < data_offset,
            )
        ):
            return FileType.ResourceFile, reader
        else:
            return FileType.AssetsFile, reader


def parse_file(
    reader: EndianBinaryReader,
    parent: files.File,
    name: str,
    typ: Optional[FileType] = None,
    is_dependency: bool = False,
    type_filter=None,
    progress_callback=None,
    object_count_only=False
) -> Union[files.File, EndianBinaryReader]:
    if typ is None:
        typ, _ = check_file_type(reader)
    f = reader
    try:
        if typ == FileType.AssetsFile and not name.endswith(
            (
                ".resS",
                ".resource",
                ".config",
                ".xml",
                ".dat",
            )
        ):
            f = files.SerializedFile(reader, parent, name=name, is_dependency=is_dependency, type_filter=type_filter, object_count_only=object_count_only)
        elif typ == FileType.BundleFile:
            f = files.BundleFile(reader, parent, name=name, is_dependency=is_dependency, progress_callback=progress_callback, object_count_only=object_count_only, type_filter=type_filter)
        elif typ == FileType.WebFile:
            f = files.WebFile(reader, parent, name=name, is_dependency=is_dependency)
    except Exception as e:
        reader.seek(0)
        # DEBUG, not print(): re-raised right after, so the caller always sees this
        # error too (and this project's own app already reports it, formatted, from
        # there) — printing here as well was pure duplicate noise.
        logger.debug("Error parsing file %r as %s: %s", name, typ, e)
        raise e
    return f


def find_sensitive_path(dir: str, insensitive_path: str) -> Union[str, None]:
    parts = os.path.split(insensitive_path.strip(os.path.sep))

    sensitive_path = dir
    for part in parts:
        part_lower = part.lower()
        part = next(
            (name for name in os.listdir(sensitive_path) if name.lower() == part_lower),
            None,
        )
        if part is None:
            return None
        sensitive_path = os.path.join(sensitive_path, part)

    return sensitive_path
