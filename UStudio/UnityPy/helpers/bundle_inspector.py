import os
from dataclasses import dataclass, field
from typing import Set, List

from .. import files
from ..enums import FileType
from ..streams import EndianBinaryReader
from ..helpers.ImportHelper import check_file_type


def format_size(size_bytes: int) -> str:
    """Generic byte formatting into B, KB, MB, GB, etc."""
    if size_bytes == 0:
        return "0 Б"
    units = ["Б", "КБ", "МБ", "ГБ", "ТБ"]
    i = 0
    val = float(size_bytes)
    while val >= 1024 and i < len(units) - 1:
        val /= 1024
        i += 1
    if i == 0:
        return f"{int(val)} {units[i]}"
    return f"{val:.1f} {units[i]}"


@dataclass
class QuickScanResult:
    disk_size_bytes: int = 0
    decompressed_size_bytes: int = 0
    object_count: int = 0
    class_ids: Set[int] = field(default_factory=set)
    is_legacy_eager: bool = False   # UnityWeb/UnityRaw — can't be cheaply scanned
    is_unscanned_web_file: bool = False  # WebFile (UnityWebData/TuanjieWebData) — not yet wired into object_count_only
    # For a BundleFile: the internal cab entry names this bundle declares (bundle.files'
    # own keys — already in memory below, just never kept before). Added so a folder-mode
    # scan can build core.addressables_resolver.CabIndex as a free byproduct of a pass it
    # already runs, instead of a second, separate whole-folder scan — see that module's
    # own docstring for why cross-bundle (Addressables-style) references need this at
    # all. A plain AssetsFile has no internal entries of its own, so this stays empty
    # for that branch — its own name (the file path) is what a dependency search for
    # THAT file would already find as a loose file, unaffected by this addition.
    cab_names: List[str] = field(default_factory=list)


def quick_scan_bundle_contents(path: str) -> QuickScanResult:
    """Near-free summary of a file: object_count, class_ids and decompressed size —
    without reading the object table and without decompressing the bundle's blocks
    (see object_count_only=True in SerializedFile/BundleFile)."""
    result = QuickScanResult(disk_size_bytes=os.path.getsize(path))

    with open(path, "rb") as f:
        signature = f.read(20).split(b"\x00")[0].decode("ascii", errors="ignore")

    if signature in ("UnityWeb", "UnityRaw"):
        result.is_legacy_eager = True
        return result

    # pass the path as a string directly to check_file_type to keep the fast mmap branch
    typ, reader = check_file_type(path)

    if typ == FileType.BundleFile:
        bundle = files.BundleFile(reader, parent=None, name=path, object_count_only=True)
        result.decompressed_size_bytes = getattr(bundle, "decompressed_size", 0)
        result.cab_names = list(bundle.files.keys())
        for f in bundle.files.values():
            if isinstance(f, files.SerializedFile):
                result.object_count += f.object_count
                result.class_ids |= f.class_ids
    elif typ == FileType.AssetsFile:
        sf = files.SerializedFile(reader, parent=None, name=path, object_count_only=True)
        result.object_count = sf.object_count
        result.class_ids = sf.class_ids
        result.decompressed_size_bytes = result.disk_size_bytes
    elif typ == FileType.WebFile:
        # object_count_only isn't wired into WebFile's internal SerializedFiles — rather
        # than silently reporting 0 objects (which would never trigger the large-file
        # warning dialogs), flag it so callers know this scan didn't actually cover it.
        result.is_unscanned_web_file = True

    return result


def _object_record_size(version: int, big_id_enabled: bool) -> "tuple[int, bool]":
    """Computes the byte size of one (unaligned) ObjectInfo record in the object table
    for a given SerializedFile header version, and whether align_stream() must run
    before it. Used only to SKIP the object table's bytes in object_count_only mode
    (see SerializedFile.__init__) — never to parse it — so this is plain arithmetic,
    not a numpy dtype: endianness doesn't affect a field's byte width, only how its
    bytes would be interpreted, which is irrelevant when we're just seeking past them.
    """
    needs_align = (version >= 14) and not big_id_enabled

    size = 8 if (big_id_enabled or version >= 14) else 4  # path_id
    size += 8 if version >= 22 else 4                     # byte_start
    size += 4                                             # byte_size
    size += 4                                             # type_id

    if version < 16:
        size += 2  # inline class_id
    if version < 11:
        size += 2  # is_destroyed
    if 11 <= version < 17:
        size += 2  # script_type_index
    if version in (15, 16):
        size += 1  # is_stripped

    return size, needs_align
