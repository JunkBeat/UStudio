"""PyQt-free file/path/formatting utilities used by both the loader and the CAB
archive logic (and, previously, defined directly in the app's helpers.py — moved
here so core/ stays importable without PyQt6; helpers.py re-exports these names so
existing `from helpers import ...` call sites elsewhere in the app are unaffected)."""

from core.i18n import tr
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.script_signatures import recognise as recognise_script

logger = logging.getLogger("ustudio.core.file_utils")


def shorten_path(path: str, base: Optional[str] = None) -> str:
    """Formats a path for display in a log message: forward slashes throughout
    (Windows os.walk()/os.path.join() results mix in backslashes, and a path like
    "...Unity samples/Truck-kun\\MonoBleedingEdge\\etc\\..." with both separators in
    one string reads far worse than either alone), and — when it's actually inside
    `base` (typically the current load's root folder) — shown relative to base
    instead of as a full absolute path, since the common prefix carries no
    information once you already know what's being loaded. Falls back to the plain
    forward-slash-normalized absolute path when `base` isn't given or doesn't
    contain it."""
    p = Path(path)
    if base:
        try:
            return p.resolve().relative_to(Path(base).resolve()).as_posix()
        except (ValueError, OSError):
            pass
    return p.as_posix()


def safe_join(base: Path, name: str) -> Path:
    """Joins base/name and guarantees the result stays inside base. Defends against a
    name containing ".." segments, or being an absolute path outright — pathlib's `/`
    operator silently discards the left operand entirely when the right side is
    absolute (`Path("C:/out") / "C:/Windows/evil.dll"` == `C:/Windows/evil.dll`, not
    an error) — either of which would let an untrusted archive entry name (a bundle's
    internal file list is attacker-controlled the moment the bundle itself is: a
    crafted/modded/tampered file, not something this app generates) write or read
    outside the folder the user actually picked. Mirrors the safe pattern
    Environment.save() already uses (ntpath.basename) but preserves legitimate
    subdirectory structure in a name instead of flattening it. Raises ValueError
    rather than silently sanitizing — a name that needs this rejected is a sign of a
    malicious/corrupt input worth surfacing, not quietly working around."""
    base = Path(base).resolve()
    target = (base / name).resolve()
    if not target.is_relative_to(base):
        raise ValueError(f"Unsafe path outside destination folder: {name!r}")
    return target


def stream_to_file(stream, out_path, chunk_size=1024 * 1024, progress_callback=None, should_cancel=None) -> int:
    """Streams the contents of stream (an object with .Position/.Length/.read(), e.g. EndianBinaryReader
    or a window into a bundle) to a file on disk, without loading everything into memory at once.
    Returns the number of bytes written.

    should_cancel, if given, is checked before every chunk and raises InterruptedError to
    abort the copy early — mirrors the should_cancel pattern used elsewhere in this project
    (e.g. BundleFile.save_to_file/write_to_stream) so a single very large entry can actually
    be interrupted mid-copy, not just between whole files. The partially-written out_path
    is removed whenever the copy doesn't finish cleanly — cancellation, a mid-write OSError
    (e.g. the disk filling up), or anything else — rather than left as a truncated,
    misleading file only in the cancel case."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stream.Position = 0
    remaining = stream.Length
    written = 0
    completed = False
    try:
        with open(out_path, "wb") as out:
            while remaining > 0:
                if should_cancel is not None and should_cancel():
                    raise InterruptedError(tr("Отменено пользователем"))
                chunk = bytes(stream.read(min(chunk_size, remaining)))
                if not chunk:
                    break
                out.write(chunk)
                written += len(chunk)
                remaining -= len(chunk)
                if progress_callback:
                    progress_callback(written, stream.Length)
        completed = True
    finally:
        if not completed and out_path.exists():
            try:
                out_path.unlink()
            except OSError:
                pass
    return written


def write_entry_safely(stream, base_dir, name, **stream_to_file_kwargs) -> int:
    """Combines safe_join()+stream_to_file() — the pattern every "write an archive
    entry whose name comes from untrusted bundle data" call site needs, previously
    duplicated at each of its 3 call sites (each pairing the two calls by convention,
    not by a shared helper). Raises ValueError (from safe_join) for a name that would
    resolve outside base_dir, before anything is written."""
    out_path = safe_join(base_dir, name)
    return stream_to_file(stream, out_path, **stream_to_file_kwargs)


def _mac_app_data_dir(path: Path):
    """A macOS game's data folder, X.app/Contents/Resources/Data, when `path` is the app bundle, lies inside
    it, or is a folder holding exactly one such bundle. macOS builds have no *_Data folder."""
    def data_of(app: Path):
        data = app / "Contents" / "Resources" / "Data"
        return data if data.is_dir() else None

    for p in (path, *path.parents):
        if p.suffix.lower() == ".app":
            return data_of(p)
    if path.is_dir():
        apps = [d for d in (data_of(p) for p in path.iterdir() if p.is_dir() and p.suffix.lower() == ".app") if d]
        if len(apps) == 1:
            return apps[0]
    return None


_UNITY_DATA_MARKERS = ("globalgamemanagers", "data.unity3d", "mainData")
_SWITCH_SEARCH_DEPTH = 3


def _is_unity_data(folder: Path) -> bool:
    return any((folder / name).is_file() for name in _UNITY_DATA_MARKERS)


def _switch_data_dir(path: Path):
    """A Nintendo Switch game unpacked with a separate tool (its .nsp/.xci cannot be read without the console's
    keys): the data is a folder named just «Data» inside the romfs folder, e.g. `<nca>/1 [romfs]/Data` (hactoolnet
    naming) or `romfs/Data`. Found from that folder, from inside it, or from up to _SWITCH_SEARCH_DEPTH levels above
    (the game folder, the NCA folder, romfs) when exactly one such folder is there. Only a «Data» folder that holds
    Unity data counts."""
    for p in (path, *path.parents):
        if p.name == "Data" and p.is_dir() and _is_unity_data(p):
            return p
    if not path.is_dir():
        return None
    found = []
    level = [path]
    for _ in range(_SWITCH_SEARCH_DEPTH):
        nxt = []
        for folder in level:
            try:
                children = [c for c in folder.iterdir() if c.is_dir()]
            except OSError:
                continue
            for c in children:
                if c.name == "Data" and _is_unity_data(c):
                    found.append(c)
                else:
                    nxt.append(c)
        level = nxt
    return found[0] if len(found) == 1 else None


def detect_game_paths(selected_path: Path) -> dict:
    """Looks for a *_Data folder next to the given path (on macOS: the app bundle's Contents/Resources/Data; on an
    unpacked Nintendo Switch game: romfs/Data) and,
    if found, a Managed folder inside it and the game root (the folder containing the .exe) outside it. A pure function with no side
    effects — main.py's update_game_paths() wraps it and applies the result to CONFIG; this logic
    is also needed elsewhere (e.g. CabArchive — for setting up typetree_generator when
    browsing an arbitrary archive, without tying it to the global CONFIG)."""
    selected_path = selected_path.resolve()

    data_dir = None

    if selected_path.is_dir():
        if selected_path.name.endswith("_Data"):
            data_dir = selected_path
        else:
            data_dirs = [
                p for p in selected_path.iterdir()
                if p.is_dir() and p.name.endswith("_Data")
            ]
            if len(data_dirs) == 1:
                data_dir = data_dirs[0]

        if data_dir is None:
            for parent in (selected_path, *selected_path.parents):
                if parent.name.endswith("_Data"):
                    data_dir = parent
                    break
    else:
        for parent in selected_path.parents:
            if parent.name.endswith("_Data"):
                data_dir = parent
                break

    if data_dir is None:
        data_dir = _mac_app_data_dir(selected_path)
    switch_layout = False
    if data_dir is None:
        data_dir = _switch_data_dir(selected_path)
        switch_layout = data_dir is not None

    managed_dir = ""
    game_root_dir = ""
    is_il2cpp = False

    if data_dir:
        managed = data_dir / "Managed"
        # A Switch build's Managed holds only Metadata (IL2CPP): it is not a folder of script DLLs, and taking it
        # for one would keep the prepared IL2CPP DLLs from being used.
        if managed.is_dir() and (not switch_layout or any(managed.glob("*.dll"))):
            managed_dir = str(managed)

        root = data_dir.parent
        if any(root.glob("*.exe")):
            game_root_dir = str(root)
            # GameAssembly.dll next to the exe is the standard signal for an IL2CPP build
            # (Mono builds don't have it — their scripts live as real per-type DLLs in
            # Managed instead). Checked independently of which DLL-loading path
            # TypeTreeGenerator ends up using (see loader.py's init_typetree): if managed_dir
            # also exists and is used directly, IL2CPP would otherwise go undetected even
            # though the DLLs sitting there for a real IL2CPP build are typically just thin
            # stubs — real per-type layout requires either GameAssembly.dll + global-metadata.dat
            # or, lacking that, hand-generated "dummy" DLLs dropped into Managed in their place.
            is_il2cpp = (root / "GameAssembly.dll").is_file()
        if not is_il2cpp:
            # Linux (GameAssembly.so next to the .x86_64) and macOS (GameAssembly.dylib in the app bundle) builds:
            # no .exe, so this is decided by the binary + metadata pair itself.
            from core.il2cpp_dummy import find_inputs
            is_il2cpp = find_inputs(str(data_dir), game_root_dir) is not None

    return {
        "data_dir": str(data_dir) if data_dir else "",
        "managed_dir": managed_dir,
        "game_root_dir": game_root_dir,
        "is_il2cpp": is_il2cpp,
    }


# Real reported question, measured directly: MANY MonoBehaviour objects routinely
# reference the exact SAME script (a whole game's worth of UI components all using
# "TMP_FontAsset", say) — but resolving one had no memory of resolving the others,
# so the FULL deref()+peek_name() cost was paid again for every single row. Measured
# on a real fixture: deref() ~11 us + peek_name() ~10 us = ~25 us per call, negligible
# for one object but ~2.5s of pure repeat work at Truck-kun's real 99,109 MonoBehaviour
# scale (see CLAUDE.md's own "Load All Assets" perf section for that fixture's other,
# larger PPtr.deref() bottleneck — this is a separate, smaller cost on top of it).
#
# Keyed by (id(source SerializedFile), m_FileID, m_PathID) — the raw PPtr, before
# deref() ever runs, so a cache hit skips BOTH calls entirely, not just peek_name().
# m_FileID/m_PathID alone are NOT a safe key: m_FileID is only an INDEX into the
# SOURCE file's own externals list, so the identical (m_FileID, m_PathID) pair in a
# DIFFERENT source file can point at a completely different target — hence
# id(assetsfile) is part of the key too. Using id() (not the SerializedFile itself,
# which isn't guaranteed hashable) for a per-load-scoped cache is the same accepted
# pattern this project already uses elsewhere for exactly this reason — see
# CLAUDE.md's "ObjectReader is unhashable" section — safe because a NEW load always
# builds fresh SerializedFile instances; the id() of a discarded one being reused by
# the allocator for a genuinely different object is the same already-accepted risk
# id(obj_ref) keying already carries there, not a new one introduced here.
@dataclass(frozen=True)
class ScriptIdentity:
    """A MonoBehaviour's referenced script, at every granularity this app
    might need. class_name is MonoScript.m_ClassName specifically — NOT
    m_Name (the asset's own file name), which peek_mb_name() used to read
    instead (via peek_name(), a GENERIC "read this object's m_Name field"
    helper with no MonoScript-specific special-casing). The two are almost
    always identical by Unity convention (a script's primary component class
    usually has to match its filename to be draggable onto a GameObject in
    the Inspector) but are not guaranteed to be — confirmed for real, not
    just theorized: sampled 5,791 distinct real scripts across 8 real game
    fixtures and found exactly one genuine divergence (a Truck-kun script
    file named "Freeroam Button.cs", m_Name == "Freeroam Button", whose
    actual class is `FreeroamButton` — a C# identifier can't contain the
    space the file name has). Rare, but m_ClassName is the field that
    actually determines whether two scripts are "the same class" for
    filtering/matching/export purposes, which m_Name was never guaranteed to
    be — so it's the more correct field for THIS identity, even though it
    coincides with m_Name in the overwhelming majority of real cases.

    namespace/assembly_name are "" when genuinely absent from the object's
    own schema (an older Unity version's MonoScript, or resolution failed
    partway) — never None, so a caller can always safely f-string/compare
    them without a None-guard."""
    class_name: str
    namespace: str
    assembly_name: str
    # True when the identity was NOT read from the MonoScript but worked out from the object's own fields
    # (see _infer_identity_from_fields): the script itself is in a file that was not loaded.
    inferred: bool = False

    @property
    def qualified_name(self) -> str:
        """"Namespace.ClassName", or just the bare class name when there's no
        namespace — a C# script with no namespace is common (small/indie
        projects routinely skip them entirely), not a rare edge case worth
        flagging with a "<global>"-style placeholder on every single one."""
        return f"{self.namespace}.{self.class_name}" if self.namespace else self.class_name


_UNKNOWN_IDENTITY = ScriptIdentity(class_name="Unknown", namespace="", assembly_name="")

# What a script is recognised by when its MonoScript cannot be read - the known classes and the fields that
# identify them - lives in core/script_signatures.py. Here: reading the fields off the object, the per-node
# cache, and the identity marked `inferred`.

# id(type tree node) -> (node, inferred identity): every object of one script shares one node, so the field
# names are read once per script, not once per object. The entry keeps the node itself and the lookup
# checks `is`, so a node freed and its id() reused by another one can never return a stale answer.
_INFERRED_BY_NODE: "dict[int, tuple]" = {}
_inferred_notice_shown = False

_SCRIPT_NAME_CACHE: "dict[tuple, ScriptIdentity]" = {}
_IDENTITY_POOL: "dict[ScriptIdentity, ScriptIdentity]" = {}


def shared_identity(identity: "ScriptIdentity") -> "ScriptIdentity":
    """One object per distinct identity (the fast path builds a new one per object) — rows keep theirs
    (object_common.get_row_script_name). Bounded by the distinct scripts of a load; cleared with the cache."""
    return _IDENTITY_POOL.setdefault(identity, identity)

# Set once peek_mb_name() has already told the user about a cross-bundle reference
# failure this session (see _warn_cross_bundle_reference_once() below) — a shared
# missing bundle is typically referenced by many MonoBehaviours, and nobody wants
# the same log line repeated hundreds of times.
_cross_bundle_notice_shown = False


def reset_script_name_cache() -> None:
    """Called once a load's SerializedFile instances are about to be discarded (see
    main.py's _clear_loaded_session()) — the cache's id()-keyed entries are harmless
    dead weight past that point, not a correctness risk, but left unbounded they'd
    grow across every load a long session ever does. Also re-arms the one-time
    cross-bundle-reference notice below, so a fresh load gets its own chance to warn."""
    _SCRIPT_NAME_CACHE.clear()
    _IDENTITY_POOL.clear()
    _INFERRED_BY_NODE.clear()
    global _cross_bundle_notice_shown, _inferred_notice_shown
    _cross_bundle_notice_shown = False
    _inferred_notice_shown = False


def _warn_cross_bundle_reference_once() -> None:
    """Real reported gap: a script name failing to resolve because it lives in a
    sibling bundle UnityPy never loaded (see core/addressables_resolver.py) only
    ever showed up as a plain "Unknown" in the Script column — nothing told the
    user WHY, or that Настройки → «Разрешить ссылки в соседних бандлах...» can fix
    it. Logged (not a popup) since this can fire from inside a table cell's data()
    call — the log panel is where this project already surfaces this whole class
    of "something didn't resolve, here's what to do" event (skipped duplicates,
    cab collisions, version-fallback skips). Kept to one line, in plain terms —
    end users read this, not developers."""
    global _cross_bundle_notice_shown
    if _cross_bundle_notice_shown:
        return
    _cross_bundle_notice_shown = True
    logger.warning(
        tr("Не удалось определить имена некоторых скриптов — возможно, они хранятся в другом файле игры или "
           "в файле, который не был загружен. Вы также можете попробовать поиск ссылок в соседних бандлах (см. "
           "Настройки).")
    )


def _infer_identity_from_fields(obj) -> ScriptIdentity:
    """The script of a MonoBehaviour whose MonoScript could not be read, recognised by the fields the
    object itself has (see core/script_signatures.py), else _UNKNOWN_IDENTITY. Reads the type tree embedded
    in the file only: a file without one (nothing to look at) stays Unknown, as it always was.

    The result is marked `inferred`, is never put in _SCRIPT_NAME_CACHE (which must stay free for the
    real identity should the missing bundle be loaded later) and is announced once in the log."""
    global _inferred_notice_shown
    try:
        node = getattr(getattr(obj, "serialized_type", None), "node", None)
        if node is None:
            return _UNKNOWN_IDENTITY
        cached = _INFERRED_BY_NODE.get(id(node))
        if cached is not None and cached[0] is node:
            identity = cached[1]
        else:
            field_types = {child.m_Name: child.m_Type for child in node.m_Children}
            known = recognise_script(field_types)
            identity = ScriptIdentity(*known, inferred=True) if known else _UNKNOWN_IDENTITY
            _INFERRED_BY_NODE[id(node)] = (node, identity)
    except Exception:
        return _UNKNOWN_IDENTITY
    if identity.inferred and not _inferred_notice_shown:
        _inferred_notice_shown = True
        logger.info(
            tr("Объекты TMP_FontAsset были распознаны по составу полей.")
        )
    return identity


def peek_mb_identity(obj) -> ScriptIdentity:
    """peek_mb_identity_resolved(), and where that finds nothing, the identity recognised from the
    object's own fields (_infer_identity_from_fields) — so a font whose script bundle was not loaded is
    still a TMP_FontAsset for the SDF tools, the script filter and the Fonts quick filter."""
    identity = _peek_mb_identity_from_script(obj)
    if identity is _UNKNOWN_IDENTITY and obj:
        return _infer_identity_from_fields(obj)
    return identity


def _peek_mb_identity_from_script(obj) -> ScriptIdentity:
    """Extracts the MonoBehaviour's referenced script's full identity (class
    name, namespace, assembly) from a UnityPy object. Returns _UNKNOWN_IDENTITY
    (class_name == "Unknown") if it could not be determined — peek_mb_name()
    is a thin wrapper around this for the many existing callers that only
    ever wanted the bare class name string.

    Resolving namespace/assembly alongside the class name costs one extra
    bounded field-peek (ObjectReader.peek_dict()) beyond what resolving just
    the name already cost — negligible next to the PPtr.deref() this was
    already paying for, and cached together with the class name (same cache,
    same key) so nothing pays for it twice."""
    if not obj:
        return _UNKNOWN_IDENTITY

    try:
        st = getattr(obj, "serialized_type", None)
        if st and getattr(st, "m_ClassName", None):
            # This fast path never touches the referenced MonoScript object at
            # all (some objects' own TypeTree metadata already carries a
            # resolved class name) — but for a "ref type" (SerializedFile
            # version >= 21, see SerializedFile.py's SerializedType.parse()),
            # m_NameSpace/m_AssemblyName are read from the SAME header bytes
            # as m_ClassName, in the same conditional block, so they're
            # already sitting on this object at zero extra cost. Only when
            # they're genuinely absent (an older, non-ref-type file) do they
            # fall back to "".
            return ScriptIdentity(
                class_name=st.m_ClassName,
                namespace=getattr(st, "m_NameSpace", None) or "",
                assembly_name=getattr(st, "m_AssemblyName", None) or "",
            )

        if hasattr(obj, "parse_monobehaviour_head"):
            data = obj.parse_monobehaviour_head()
            if data and getattr(data, "m_Script", None):
                script_ptr = data.m_Script
                if getattr(script_ptr, "path_id", 0) != 0:
                    cache_key = (id(getattr(script_ptr, "assetsfile", None)),
                                 getattr(script_ptr, "file_id", None), script_ptr.path_id)
                    cached = _SCRIPT_NAME_CACHE.get(cache_key)
                    if cached is not None:
                        return cached
                    try:
                        m_script = script_ptr.deref()
                    except FileNotFoundError:
                        _warn_cross_bundle_reference_once()
                        return _UNKNOWN_IDENTITY
                    if m_script:
                        fields = m_script.peek_dict(("m_ClassName", "m_Namespace", "m_AssemblyName")) or {}
                        # m_script.peek_name() (m_Name) as a fallback ONLY when
                        # m_ClassName itself is genuinely absent from the
                        # schema — not the primary source any more, see
                        # ScriptIdentity's own docstring for why.
                        class_name = fields.get("m_ClassName") or m_script.peek_name() or "Unknown"
                        identity = ScriptIdentity(
                            class_name=class_name,
                            namespace=fields.get("m_Namespace") or "",
                            assembly_name=fields.get("m_AssemblyName") or "",
                        )
                        _SCRIPT_NAME_CACHE[cache_key] = identity
                        return identity
    except Exception:
        # Object may be corrupted or lack the expected structure
        pass

    return _UNKNOWN_IDENTITY


def peek_mb_name(obj) -> str:
    """Extracts the MonoBehaviour script's bare class name from a UnityPy
    object. Returns "Unknown" if the name could not be determined. See
    peek_mb_identity() for the namespace/assembly-qualified form."""
    return peek_mb_identity(obj).class_name


def peek_object_name(obj) -> str:
    """Generic display-name resolution for any object type — the object's own
    m_Name field (MonoBehaviour has one too, same as every other type; its
    referenced SCRIPT's class name is a separate concern, see
    core.object_preview.resolve_script_name), then the container path it's
    stored under. Returns "" if neither resolves — callers apply their own
    fallback (see core.object_preview.default_object_name's "TypeName #PathID"),
    since what "no name" should default to isn't this module's concern (it's
    PyQt-free and doesn't know about the app's naming conventions)."""
    if not obj:
        return ""

    try:
        name = obj.peek_name()
        if name:
            return name
    except Exception:
        pass

    try:
        container = obj.container
        if container:
            return Path(container).name
    except Exception:
        pass

    return ""


def read_app_info(data_dir) -> Optional[str]:
    """Reads {data_dir}/app.info (company name on line 1, product name on line 2 —
    the standard Unity standalone loose-file layout) and returns the product name,
    or None if the file is missing/unreadable/short. Used for the window title's
    "loaded project name" segment — deliberately best-effort, since a missing or
    malformed app.info isn't an error, just means that segment gets omitted."""
    if not data_dir:
        return None
    try:
        path = Path(data_dir) / "app.info"
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[1].strip() or None if len(lines) >= 2 else None
    except OSError:
        return None


def bytes_to_hex_dump_with_map(data, max_bytes=250000, target_offset=0):
    if not data:
        return tr("[Пусто]"), {}

    start_byte = 0
    if len(data) > max_bytes:
        start_byte = max(0, target_offset - 20)
        start_byte = (start_byte // 16) * 16
        end_byte = min(len(data), start_byte + max_bytes)
        data_window = data[start_byte:end_byte]
        truncated = True
    else:
        data_window = data
        truncated = False

    lines = []
    offset_to_line_index = {}

    # The truncation notice below adds 2 lines ("... [Дамп обрезан...] ...\n\n")
    # ABOVE the first data row when truncated=True — offset_to_line_index must
    # count them too, or RawViewerDialog.highlight_offset()/scroll_to_offset()
    # (which call QTextDocument.findBlockByLineNumber() with these line numbers)
    # land 2 lines too early. Real reported bug: the highlight consistently
    # landed 32 bytes (2 rows) before the actual match.
    header_lines = 2 if truncated else 0

    for line_idx, i in enumerate(range(0, len(data_window), 16)):
        chunk = data_window[i:i+16]
        actual_base_offset = start_byte + i

        for byte_pos in range(len(chunk)):
            offset_to_line_index[actual_base_offset + byte_pos] = header_lines + line_idx

        hex_part = " ".join(f"{b:02X}" for b in chunk)
        if len(chunk) < 16:
            hex_part += " " * (48 - len(hex_part))

        ascii_bytes = []
        for b in chunk:
            if b < 32 or b == 127:
                ascii_bytes.append(46)
            else:
                ascii_bytes.append(b)

        ascii_part = bytes(ascii_bytes).decode("utf-8", errors="replace").replace("\ufffd", ".")

        if len(ascii_part) < len(chunk):
            ascii_part += "." * (len(chunk) - len(ascii_part))
        elif len(ascii_part) > len(chunk):
            ascii_part = ascii_part[:len(chunk)]

        lines.append(f"{actual_base_offset:08X}  {hex_part}  |{ascii_part}|")

    result = "\n".join(lines)
    if truncated:
        result = (tr("... [Дамп обрезан. Отображается окно данных со смещения {start_byte:08X}] ...", start_byte=start_byte)
                  + "\n\n" + result)
    return result, offset_to_line_index


def format_size(size_bytes: int, english: bool = False) -> str:
    """Generic formatting of a byte count into B, KB, MB, GB, etc. — in the interface language, or always English
    (english=True: the preview's metadata line stays English in every language)."""
    if size_bytes == 0:
        return "0 B" if english else tr("0 Б")
    units = ["B", "KB", "MB", "GB", "TB"] if english else [tr("б"), tr("кб"), tr("мб"), tr("гб"), tr("тб")]
    i = 0
    val = float(size_bytes)
    while val >= 1024 and i < len(units) - 1:
        val /= 1024
        i += 1
    if i == 0:
        return f"{int(val)} {units[i]}"
    return f"{val:.1f} {units[i]}"
