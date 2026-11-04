"""Addressables catalogs: keep each bundle's CRC right after UStudio rewrites the bundle (no Qt).

An Addressables game lists every bundle in `StreamingAssets/aa/catalog.json` (or the binary `catalog.bin` of
Addressables 2.x) with load options, among them `m_Crc`. When it is not 0, Unity checks the bundle against it on
load and refuses a bundle whose content changed ("CRC Mismatch") — the modded content silently goes missing in the
game. Checked on the samples: PUSS! (18 of 18 bundles) and Deep Sleep (8 of 8) have the check on; Phonopolis, ROUNDS
and Lego party (binary catalog) have it off (all 0). The value is the CRC-32 of the bundle's DECOMPRESSED data (16 of
16 bundles of those two games match), so after a save the right value is simply recomputed and written — the game's
own check stays on, unlike tools that set it to 0.

Only records whose CRC is non-zero are touched (0 = no check); nothing else in the catalog changes. A catalog that
cannot be read is reported and left alone. The catalog formats follow nesrak1's AddressablesTools (MIT, format
reference only): JSON catalogs keep entries (7 int32: internal id, provider, dependency key, dependency hash, data
offset, primary key, resource type) and their objects in base64 strings; an AssetBundleRequestOptions object is
type 7 (1-byte assembly and class names, then a UTF-16 JSON text with an int32 byte length). Binary catalogs keep
it as a fixed record (hash, bundle name, CRC, size, common info offsets), so the CRC is patched in place."""

from __future__ import annotations

from core.i18n import tr
import base64
import json
import logging
import re
import struct
import zlib
from pathlib import Path
from typing import Dict, Iterable, List, NamedTuple, Optional, Tuple

logger = logging.getLogger(__name__)

_ABRO = "AssetBundleRequestOptions"
_RUNTIME_PATH = "{UnityEngine.AddressableAssets.Addressables.RuntimePath}"
_CRC_FIELD = re.compile(r'("m_Crc"\s*:\s*)(\d+)')
_MAX = 0xFFFFFFFF
_CHUNK = 4 * 1024 * 1024


class CatalogUpdate(NamedTuple):
    catalog_path: Path
    data: bytes          # the whole updated catalog file
    bundles: List[str]   # file names of the bundles whose CRC changed


# ---------------------------------------------------------------- bundle CRC

def bundle_crc(data: bytes) -> int:
    """CRC-32 of a bundle's decompressed data (what Addressables stores as m_Crc), streamed block by block."""
    from UnityPy.files.BundleFile import BundleFile, clear_bundle_cache
    from UnityPy.streams import EndianBinaryReader

    # No name: the block cache is keyed by it, and the loaded original of this very bundle may share it.
    bundle = BundleFile(EndianBinaryReader(data), None, object_count_only=True)
    try:
        reader = bundle.blocksReader
        reader.Position = 0
        total = reader.Length
        crc = 0
        while reader.Position < total:
            crc = zlib.crc32(reader.read_bytes(min(_CHUNK, total - reader.Position)), crc)
        return crc & _MAX
    finally:
        clear_bundle_cache(bundle._cache_id)


# ---------------------------------------------------------------- locating catalogs

def find_aa_root(path: Path) -> Optional[Path]:
    """The Addressables folder (`.../aa`) holding this file's catalog, if the file lies under one."""
    for parent in list(path.parents)[:4]:
        if parent.name.lower() == "aa" and any(_catalog_files(parent)):
            return parent
    return None


def _catalog_files(aa_root: Path) -> Iterable[Path]:
    # A catalog can also be packed into a bundle of its own (catalog.bundle: one TextAsset holding the JSON or
    # binary catalog) — some games ship it that way (user report).
    for pattern in ("catalog*.json", "catalog*.bin", "catalog*.bundle"):
        yield from sorted(aa_root.glob(pattern))


def _id_key(internal_id: str) -> str:
    """An internal id reduced to its path relative to the aa folder, lower-case with '/' separators."""
    text = internal_id.replace(_RUNTIME_PATH, "").replace("\\", "/").strip("/")
    return text.lower()


def _file_keys(path: Path, aa_root: Path) -> Tuple[str, str]:
    rel = path.relative_to(aa_root).as_posix().lower()
    return rel, path.name.lower()


# ---------------------------------------------------------------- JSON catalogs

def _read_json_catalog(raw: bytes):
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    doc = json.loads(text)
    ids = list(doc.get("m_InternalIds") or [])
    prefixes = doc.get("m_InternalIdPrefixes") or []
    if prefixes:
        for i, iid in enumerate(ids):
            head, sep, tail = iid.partition("#")
            if sep and head.isdigit() and int(head) < len(prefixes):
                ids[i] = prefixes[int(head)] + tail
    return bom, text, doc, ids


def _json_options(entries: bytes, extra: bytes, ids: List[str]):
    """{data offset: (json start, json byte length, json text, [internal ids])} for every bundle-options object."""
    count = struct.unpack_from("<i", entries, 0)[0]
    if len(entries) != 4 + count * 28:
        raise ValueError(tr("неизвестный формат записей каталога"))
    found = {}
    for i in range(count):
        iid, _prov, _dep, _hash, data_index, _pk, _type = struct.unpack_from("<7i", entries, 4 + i * 28)
        if data_index < 0 or data_index >= len(extra) or extra[data_index] != 7:
            continue
        pos = data_index + 1
        asm_len = extra[pos]
        pos += 1 + asm_len
        cls_len = extra[pos]
        cls = extra[pos + 1:pos + 1 + cls_len].decode("ascii", "replace")
        pos += 1 + cls_len
        if not cls.endswith(_ABRO):
            continue
        size = struct.unpack_from("<i", extra, pos)[0]
        rec = found.get(data_index)
        if rec is None:
            text = extra[pos + 4:pos + 4 + size].decode("utf-16-le")
            rec = found[data_index] = (pos, size, text, [])
        if 0 <= iid < len(ids):
            rec[3].append(ids[iid])
    return found


def _update_json_catalog(raw: bytes, new_crc_for) -> Tuple[Optional[bytes], List[str]]:
    bom, text, doc, ids = _read_json_catalog(raw)
    if not isinstance(doc, dict) or "m_EntryDataString" not in doc or "m_ExtraDataString" not in doc:
        return None, []  # some other JSON next to the catalog (Phonopolis has a catalog_formatted_data.json)
    entries_b64, extra_b64 = doc["m_EntryDataString"], doc["m_ExtraDataString"]
    entries = bytearray(base64.b64decode(entries_b64))
    extra = bytearray(base64.b64decode(extra_b64))
    changes = []  # (data offset, json start, old byte length, new json text, bundle name)
    for data_index, (start, size, json_text, iids) in _json_options(entries, extra, ids).items():
        match = _CRC_FIELD.search(json_text)
        if not match or int(match.group(2)) == 0:
            continue
        crc = next((c for c in (new_crc_for(i) for i in iids) if c is not None), None)
        if crc is None or crc == int(match.group(2)):
            continue
        new_text = json_text[:match.start(2)] + str(crc) + json_text[match.end(2):]
        changes.append((data_index, start, size, new_text, Path(_id_key(iids[0])).name))
    if not changes:
        return None, []

    # Splice from the end, so earlier offsets stay valid; every entry pointing past a changed object moves with it.
    count = struct.unpack_from("<i", entries, 0)[0]
    for data_index, start, size, new_text, _name in sorted(changes, reverse=True):
        body = new_text.encode("utf-16-le")
        extra[start:start + 4 + size] = struct.pack("<i", len(body)) + body
        delta = len(body) - size
        if delta:
            for i in range(count):
                off = 4 + i * 28 + 16
                value = struct.unpack_from("<i", entries, off)[0]
                if value > data_index:
                    struct.pack_into("<i", entries, off, value + delta)

    new_text_doc = text
    for old, new in ((entries_b64, base64.b64encode(bytes(entries)).decode("ascii")),
                     (extra_b64, base64.b64encode(bytes(extra)).decode("ascii"))):
        if new_text_doc.count(old) != 1:
            raise ValueError(tr("не удалось однозначно найти данные в тексте каталога"))
        new_text_doc = new_text_doc.replace(old, new)
    out = new_text_doc.encode("utf-8")
    return (b"\xef\xbb\xbf" + out if bom else out), [c[4] for c in changes]


# ---------------------------------------------------------------- binary catalogs

class _BinaryCatalog:
    def __init__(self, data: bytearray):
        self.data = data
        _magic, self.version = struct.unpack_from("<ii", data, 0)
        if not 1 <= self.version <= 3:
            raise ValueError(tr("неизвестная версия двоичного каталога: {version}", version=self.version))
        self.keys_offset = struct.unpack_from("<I", data, 8)[0]

    def u32s(self, off: int, n: int):
        return struct.unpack_from(f"<{n}I", self.data, off)

    def offsets(self, enc: int) -> List[int]:
        if enc == _MAX:
            return []
        n = struct.unpack_from("<i", self.data, enc - 4)[0] // 4
        return list(self.u32s(enc, n))

    def string(self, enc: int, sep: str = "/") -> str:
        if enc == _MAX:
            return ""
        unicode = bool(enc & 0x80000000)
        off = enc & 0x3FFFFFFF
        if enc & 0x40000000:
            parts = []
            while True:
                part, nxt = self.u32s(off, 2)
                parts.append(self.string(part, sep))
                if nxt == _MAX:
                    break
                off = nxt
            if self.version > 1:
                parts.reverse()
            return sep.join(parts)
        n = struct.unpack_from("<i", self.data, off - 4)[0]
        return bytes(self.data[off:off + n]).decode("utf-16-le" if unicode else "ascii", "replace")

    def options(self) -> Dict[int, Tuple[int, List[str]]]:
        """{offset of the CRC field: (crc, [internal ids])} for every bundle-options record."""
        found: Dict[int, Tuple[int, List[str]]] = {}
        seen = set()
        pending = []
        pairs = self.offsets(self.keys_offset)
        for i in range(1, len(pairs), 2):
            pending.extend(self.offsets(pairs[i]))
        while pending:
            loc = pending.pop()
            if loc in seen:
                continue
            seen.add(loc)
            _pk, iid, _prov, deps, _dh, data_off, _type = struct.unpack_from("<IIIIiII", self.data, loc)
            pending.extend(self.offsets(deps))
            if data_off == _MAX:
                continue
            type_off, obj_off = self.u32s(data_off, 2)
            if obj_off == _MAX or _ABRO not in self.string(self.u32s(type_off, 2)[1], "."):
                continue
            crc_off = obj_off + 8
            rec = found.setdefault(crc_off, (self.u32s(crc_off, 1)[0], []))
            rec[1].append(self.string(iid, "/"))
        return found


def _update_binary_catalog(raw: bytes, new_crc_for) -> Tuple[Optional[bytes], List[str]]:
    catalog = _BinaryCatalog(bytearray(raw))
    names = []
    for crc_off, (old, iids) in catalog.options().items():
        if old == 0:
            continue
        crc = next((c for c in (new_crc_for(i) for i in iids) if c is not None), None)
        if crc is None or crc == old:
            continue
        struct.pack_into("<I", catalog.data, crc_off, crc)
        names.append(Path(_id_key(iids[0])).name)
    return (bytes(catalog.data) if names else None), names


def _update_catalog_bytes(raw: bytes, new_crc_for) -> Tuple[Optional[bytes], List[str]]:
    """A catalog's own bytes: binary when they start with the binary magic, JSON otherwise."""
    if raw[:4] in (b"\x42\x89\xe3\x0d", b"\x0d\xe3\x89\x42"):
        return _update_binary_catalog(raw, new_crc_for)
    return _update_json_catalog(raw, new_crc_for)


def _update_bundled_catalog(raw: bytes, new_crc_for) -> Tuple[Optional[bytes], List[str]]:
    """catalog.bundle: the catalog is the text of the bundle's only TextAsset; the bundle is saved back with its
    original compression."""
    import UnityPy

    env = UnityPy.load(raw)
    texts = [obj for obj in env.objects if obj.type.name == "TextAsset"]
    if len(texts) != 1:
        return None, []  # an ordinary bundle that merely has "catalog" in its name
    asset = texts[0].read()
    script = asset.m_Script
    inner = script.encode("utf-8", "surrogateescape") if isinstance(script, str) else bytes(script)
    is_binary = inner[:4] in (b"\x42\x89\xe3\x0d", b"\x0d\xe3\x89\x42")
    if not is_binary and b"m_ExtraDataString" not in inner:
        return None, []  # a TextAsset that is not a catalog
    new_inner, names = _update_catalog_bytes(inner, new_crc_for)
    if new_inner is None:
        return None, []
    asset.m_Script = new_inner.decode("utf-8", "surrogateescape") if isinstance(script, str) else new_inner
    asset.save()
    return env.file.save(packer="original"), names


# ---------------------------------------------------------------- entry point

def describe(update: CatalogUpdate) -> str:
    """The log line for one updated catalog (end-user wording)."""
    # n = len(update.bundles)
    return (tr("{name} обновлён", name=update.catalog_path.name))


def catalog_updates(saved: Dict[Path, bytes]) -> Tuple[List[CatalogUpdate], List[str]]:
    """For bundles about to be written ({original path: new bytes}): the catalogs whose CRCs must change, already
    updated in memory, plus plain-language problems (a catalog that could not be read is left as it is). Bundles
    outside an Addressables folder are ignored, so this is a no-op for every other game."""
    by_root: Dict[Path, Dict[Path, bytes]] = {}
    for path, data in saved.items():
        root = find_aa_root(Path(path))
        if root is not None:
            by_root.setdefault(root, {})[Path(path)] = data

    updates: List[CatalogUpdate] = []
    problems: List[str] = []
    for root, bundles in by_root.items():
        keyed = {}
        for path, data in bundles.items():
            rel, name = _file_keys(path, root)
            keyed[rel] = keyed[name] = data
        cache: Dict[int, int] = {}

        def new_crc_for(internal_id: str) -> Optional[int]:
            key = _id_key(internal_id)
            data = keyed.get(key)
            if data is None:
                data = keyed.get(key.rsplit("/", 1)[-1])
            if data is None:
                return None
            if id(data) not in cache:
                cache[id(data)] = bundle_crc(data)
            return cache[id(data)]

        for catalog_path in _catalog_files(root):
            try:
                raw = catalog_path.read_bytes()
                if catalog_path.suffix.lower() == ".bundle":
                    new, names = _update_bundled_catalog(raw, new_crc_for)
                else:
                    new, names = _update_catalog_bytes(raw, new_crc_for)
            except Exception as e:
                logger.debug("Addressables catalog %s not updated", catalog_path, exc_info=True)
                problems.append(tr("{name} не удалось обновить: {error}", name=catalog_path.name, error=e))
                continue
            if new is not None:
                updates.append(CatalogUpdate(catalog_path, new, names))
    return updates, problems
