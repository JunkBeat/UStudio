"""Dummy DLLs for IL2CPP games: running the bundled Il2CppDumper and caching what it makes.

An IL2CPP game has no Managed folder of real script DLLs; its MonoBehaviour layouts live in GameAssembly.dll +
global-metadata.dat. TypeTreeGenerator reads those directly for most games, but not for metadata v38/v39 (Unity 6:
"failed to load il2cpp") — there the only route is "dummy" DLLs made by Il2CppDumper (the patched fork in
bundled_tools/il2cpp_dumper, see its README.txt). Measured on the samples: 5-23 s per game, 7-10 MB of DLLs.

Platforms: the dumper reads Windows PE, Linux/Android ELF (64- and 32-bit ARM too, which the native reader cannot)
and macOS Mach-O; a universal macOS binary is cut down to one slice first (macho_slice — the dumper would ask on its
console which one). find_inputs knows the desktop layouts (GameAssembly.dll / .so next to the executable,
GameAssembly.dylib in X.app/Contents/Frameworks) and an unpacked Nintendo Switch game (the NSO «main» in exefs +
romfs/Data/Managed/Metadata); an Android package gives its pair explicitly.

Nothing is written into the game folder: the DLLs go to %LOCALAPPDATA%/UStudio/il2cpp_cache/<key>/DummyDll, where
<key> comes from the two input files' paths, sizes and modification times (a game update -> a new key). The loader
looks there by itself (cached_dummy_dir) — a game's own Managed folder still wins.

What the dumper does NOT tell us through its exit code (it is always 0): success is read from its output and from
the DummyDll folder. Two things to know about how it runs:
  * When it cannot find the script registration by reading the file (the normal case for v38/v39), it LOADS
    GameAssembly.dll into its own process (LoadLibrary), which runs the game's DLL start-up code and needs the game's
    other DLLs (baselib.dll, ...) — so it runs with the game folder as its working directory.
  * It may ask for addresses on the console in manual mode; stdin is closed, so those questions fail instead of
    waiting forever, and there is a timeout on top.
No PyQt here (core/)."""

from core.i18n import tr
import hashlib
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from .platform_sources import cache_base

logger = logging.getLogger("ustudio.il2cpp")

TOOL_DIR = Path(__file__).resolve().parent.parent / "bundled_tools" / "il2cpp_dumper"
TOOL_EXE = "Il2CppDumper.exe"
# Bumped when the bundled dumper or its config changes in a way that changes its output: old cache entries are
# then no longer used (their key differs).
TOOL_REVISION = "v39fixes-net48-1"
METADATA_MAGIC = b"\xaf\x1b\xb1\xfa"          # 0xFAB11BAF, little-endian — what an unencrypted metadata file starts with
DEFAULT_TIMEOUT_S = 15 * 60
_MARKER = "ustudio.json"
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class DumperError(Exception):
    """A failed generation. str() is the message for the user; `details` is the tail of the dumper's output."""

    def __init__(self, message: str, details: str = ""):
        super().__init__(message)
        self.details = details


class DumperCancelled(Exception):
    pass


@dataclass(frozen=True)
class Il2CppInputs:
    binary: Path          # GameAssembly.dll/.so/.dylib (or libil2cpp.so from an unpacked Android package)
    metadata: Path        # global-metadata.dat
    work_dir: Path        # the dumper's working directory: the game folder, where GameAssembly.dll's own DLLs are

    @property
    def is_nso(self) -> bool:
        """A Nintendo Switch executable: only the dumper reads it (the native reader does not know NSO)."""
        return _is_nso(self.binary)

    @property
    def is_windows_binary(self) -> bool:
        """GameAssembly.dll: the native reader takes it through load_local_game (the game folder); every other
        platform's binary is handed over as bytes (loader.init_typetree)."""
        return self.binary.suffix.lower() == ".dll"


def _desktop_binaries(data: Path, root: Path):
    """Where a desktop build keeps its IL2CPP binary, given its data folder: Windows and Linux next to the
    executable (GameAssembly.dll / GameAssembly.so), macOS in the app bundle's Frameworks folder
    (X.app/Contents/Resources/Data -> X.app/Contents/Frameworks/GameAssembly.dylib)."""
    yield root / "GameAssembly.dll"
    yield root / "GameAssembly.so"
    if data.parent.name == "Resources" and data.parent.parent.name == "Contents":
        yield data.parent.parent / "Frameworks" / "GameAssembly.dylib"


_NSO_MAGIC = b"NSO0"


def _is_nso(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == _NSO_MAGIC
    except OSError:
        return False


def _switch_binaries(data: Path):
    """A Nintendo Switch game's IL2CPP code is the NSO named «main» in the exefs folder, a sibling of the romfs
    folder that holds Data: `<nca>/0 [pfs0]/main` next to `<nca>/1 [romfs]/Data` (hactoolnet naming), or
    `exefs/main` next to `romfs/Data`. Checked by its NSO0 signature (rtld/sdk/subsdk* are the system's NSOs)."""
    romfs = data.parent
    candidates = [romfs / "main"]
    try:
        candidates += [d / "main" for d in sorted(romfs.parent.iterdir()) if d.is_dir() and d != romfs]
    except OSError:
        pass
    for binary in candidates:
        if binary.is_file() and _is_nso(binary):
            yield binary


def find_inputs(game_data_dir: str = "", game_root_dir: str = "", il2cpp_binary: str = "",
                il2cpp_metadata: str = "") -> Optional[Il2CppInputs]:
    """The two files the dumper needs, from the same fields the loader options carry; None when it is not an IL2CPP
    game (or the files are not there). An explicit binary/metadata pair (an unpacked Android package) wins."""
    if il2cpp_binary and il2cpp_metadata:
        binary, metadata = Path(il2cpp_binary), Path(il2cpp_metadata)
        if binary.is_file() and metadata.is_file():
            return Il2CppInputs(binary, metadata, binary.parent)
        return None
    if not game_data_dir:
        return None
    data = Path(game_data_dir)
    root = Path(game_root_dir) if game_root_dir else data.parent     # a copied game without its .exe still works
    metadata = data / "il2cpp_data" / "Metadata" / "global-metadata.dat"
    if metadata.is_file():
        for binary in _desktop_binaries(data, root):
            if binary.is_file():
                return Il2CppInputs(binary, metadata, binary.parent)
        return None
    metadata = data / "Managed" / "Metadata" / "global-metadata.dat"          # Nintendo Switch (and Android) layout
    if metadata.is_file():
        for binary in _switch_binaries(data):
            return Il2CppInputs(binary, metadata, binary.parent)
    return None


_FAT_MAGICS = {b"\xca\xfe\xba\xbe": False, b"\xca\xfe\xba\xbf": True}     # big-endian fat header -> 64-bit offsets
_MACHO_64 = b"\xcf\xfa\xed\xfe"                                            # MH_MAGIC_64, little-endian
_CPU_ARM64, _CPU_X86_64 = 0x0100000C, 0x01000007


def macho_slice(path: Path) -> Optional[bytes]:
    """The 64-bit Mach-O inside a universal ("fat") macOS binary, or None when the file is not one. Il2CppDumper
    asks on its console which slice to take (and fails without a console), and the native reader expects one
    architecture — so the slice is cut out here. ARM64 first (the most used IL2CPP code path), then x86_64."""
    with open(path, "rb") as fh:
        head = fh.read(8)
        wide = _FAT_MAGICS.get(head[:4])
        if wide is None:
            return None
        count = int.from_bytes(head[4:8], "big")
        if not 0 < count <= 16:
            return None
        size = 32 if wide else 20
        table = fh.read(count * size)
        slices = {}
        for i in range(count):
            rec = table[i * size:(i + 1) * size]
            cpu = int.from_bytes(rec[0:4], "big")
            if wide:
                offset, length = int.from_bytes(rec[8:16], "big"), int.from_bytes(rec[16:24], "big")
            else:
                offset, length = int.from_bytes(rec[8:12], "big"), int.from_bytes(rec[12:16], "big")
            slices.setdefault(cpu, (offset, length))
        for cpu in (_CPU_ARM64, _CPU_X86_64):
            if cpu in slices:
                offset, length = slices[cpu]
                fh.seek(offset)
                data = fh.read(length)
                if len(data) == length and data[:4] == _MACHO_64:
                    return data
    return None


def binary_bytes(inputs: Il2CppInputs) -> bytes:
    """The IL2CPP binary as the native reader takes it: a universal macOS binary reduced to one slice."""
    return macho_slice(inputs.binary) or inputs.binary.read_bytes()


def metadata_problem(metadata: Path) -> str:
    """A message when the metadata file is not one the dumper can read (encrypted / modified), else ""."""
    try:
        with open(metadata, "rb") as fh:
            head = fh.read(4)
    except OSError as e:
        return tr("Не удалось прочитать файл данных скриптов: {error}", error=e)
    if head != METADATA_MAGIC:
        return (tr("Данные скриптов этой игры зашифрованы или изменены разработчиком, поэтому подготовить их "
           "автоматически не получится."))
    return ""


_FINGERPRINT_SAMPLE = 1 << 20                      # bytes hashed at each end of a file
_fingerprints: dict = {}                            # (path, size, mtime) -> fingerprint, for this process


def _file_fingerprint(path: Path) -> str:
    """What a file IS, not where it lies: its size and a hash of its first and last MiB. A build differs there
    (GameAssembly.dll's PE header carries the build stamp, global-metadata.dat's header the table offsets/sizes).
    Remembered per path/size/mtime, so repeated lookups (every load, the preview's «Исправить» check) read nothing."""
    st = path.stat()
    memo = (os.path.normcase(str(path.resolve())), st.st_size, st.st_mtime_ns)
    known = _fingerprints.get(memo)
    if known is not None:
        return known
    h = hashlib.sha1(str(st.st_size).encode("ascii"))
    with open(path, "rb") as fh:
        h.update(fh.read(_FINGERPRINT_SAMPLE))
        if st.st_size > _FINGERPRINT_SAMPLE:
            fh.seek(max(_FINGERPRINT_SAMPLE, st.st_size - _FINGERPRINT_SAMPLE))
            h.update(fh.read(_FINGERPRINT_SAMPLE))
    _fingerprints[memo] = fingerprint = h.hexdigest()
    return fingerprint


def cache_key(inputs: Il2CppInputs) -> str:
    """The cache folder name for a game's two files. Built from their CONTENT, not their paths (user report,
    2026-10-16: moving the samples into another folder threw every prepared game away — the key held full paths),
    so moving, renaming or copying the game keeps its prepared DLLs."""
    parts = [TOOL_REVISION, _file_fingerprint(inputs.binary), _file_fingerprint(inputs.metadata)]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]      # short: see the path note in generate


def _legacy_cache_key(inputs: Il2CppInputs) -> str:
    """The key used up to 2026-10-16 (paths + sizes + mtimes) — only to adopt entries prepared under it."""
    parts = [TOOL_REVISION]
    for p in (inputs.binary, inputs.metadata):
        st = p.stat()
        parts += [os.path.normcase(str(p.resolve())), str(st.st_size), str(st.st_mtime_ns)]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _adopt_legacy_entry(inputs: Il2CppInputs, entry: Path) -> None:
    """An entry prepared under the old key (game still where it was) is renamed to the new key, so nobody has to
    prepare again after this change. Best effort: on any failure the game simply counts as not prepared."""
    try:
        legacy = cache_root() / _legacy_cache_key(inputs)
        if legacy != entry and (legacy / _MARKER).is_file() and not entry.exists():
            legacy.rename(entry)
    except OSError:
        pass


def cache_root() -> Path:
    return cache_base("il2cpp")


def cached_dummy_dir(inputs: Optional[Il2CppInputs]) -> Optional[Path]:
    """The finished DummyDll folder for these inputs, or None. Only a complete run leaves the marker file."""
    if inputs is None:
        return None
    try:
        entry = cache_root() / cache_key(inputs)
    except OSError:
        return None
    if not (entry / _MARKER).is_file():
        _adopt_legacy_entry(inputs, entry)
    dummy = entry / "DummyDll"
    if (entry / _MARKER).is_file() and dummy.is_dir() and any(dummy.glob("*.dll")):
        return dummy
    return None


def cache_entries() -> List[Path]:
    """The prepared games in the cache (one folder each)."""
    root = cache_root()
    return sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []


def _folder_size(folder: Path) -> int:
    return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())


def cache_size() -> int:
    return sum(_folder_size(p) for p in cache_entries())


def clear_cache(keep=()) -> int:
    """Removes every prepared game except the folders in `keep` (a cache entry or its DummyDll); returns bytes freed.
    Settings -> «Очистить кэш IL2CPP...». A removed game is simply prepared again when needed."""
    keep_dirs = set()
    for k in keep:
        k = Path(k)
        keep_dirs.add(os.path.normcase(str((k.parent if k.name == "DummyDll" else k).resolve())))
    freed = 0
    for entry in cache_entries():
        if os.path.normcase(str(entry.resolve())) in keep_dirs:
            continue
        size = _folder_size(entry)
        shutil.rmtree(entry, ignore_errors=True)
        if not entry.exists():
            freed += size
    return freed


def tool_path() -> Path:
    return TOOL_DIR / TOOL_EXE


def _classify_failure(output: str) -> str:
    """The dumper's own wording -> what the user is told (it never sets an exit code)."""
    if "Metadata file not found or encrypted" in output:
        return (tr("Данные скриптов этой игры зашифрованы или изменены разработчиком, поэтому подготовить их "
           "автоматически не получится."))
    if "PathTooLongException" in output or ("DirectoryNotFoundException" in output and "DummyDll" in output):
        return (tr("Не удалось записать файлы: слишком длинный путь к папке программы ({cache_root}). Сократите "
           "путь к папке пользователя или перенесите её.", cache_root=cache_root()))
    if "32-bit file" in output:
        return tr("Это 32-битная игра, а автоматическая подготовка работает только с 64-битными играми.")
    if "custom PE loader" in output and "Win32Exception" in output:
        return (tr("Не удалось запустить код игры для анализа: в папке игры не хватает её файлов (например, "
           "baselib.dll или UnityPlayer.dll). Нужна полная установленная копия игры."))
    if "Can't use auto mode" in output or "Input CodeRegistration" in output:
        return (tr("Не удалось найти данные скриптов в файлах игры — игра, вероятно, защищена от анализа. "
           "Подготовить скрипты автоматически не получится."))
    return tr("Не удалось подготовить скрипты игры. Подробности записаны в журнал.")


def generate(inputs: Il2CppInputs, should_cancel: Callable[[], bool] = lambda: False,
             on_line: Optional[Callable[[str], None]] = None, timeout_s: float = DEFAULT_TIMEOUT_S) -> Path:
    """Runs the dumper for `inputs` and returns the cached DummyDll folder. Raises DumperError (with a plain-language
    message) or DumperCancelled. A cached result for the same inputs is replaced."""
    problem = metadata_problem(inputs.metadata)
    if problem:
        raise DumperError(problem)
    exe = tool_path()
    if not exe.is_file():
        raise DumperError(tr("Не найден встроенный инструмент: {exe}", exe=exe))

    root = cache_root()
    root.mkdir(parents=True, exist_ok=True)
    key = cache_key(inputs)
    # Kept SHORT on purpose: the .NET Framework build cannot write a path over 260 characters (found with a deep
    # %LOCALAPPDATA%: <key>.partial-<pid>\out\DummyDll\UnityEngine.UnityWebRequestAssetBundleModule.dll failed).
    work = root / f"t{os.getpid()}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        binary = inputs.binary
        piece = macho_slice(binary)
        if piece is not None:                          # a universal macOS binary: the dumper gets one slice
            binary = work / ("slice" + binary.suffix)
            binary.write_bytes(piece)
            del piece
        output = _run(exe, binary, inputs, work, should_cancel, on_line, timeout_s)
        dummy = work / "DummyDll"
        dlls = sorted(p.name for p in dummy.glob("*.dll")) if dummy.is_dir() else []
        if not dlls or "ERROR: Some errors in generating dummy dll" in output or "Generate dummy dll" not in output:
            raise DumperError(_classify_failure(output), details=output[-4000:])
        for extra in work.iterdir():                   # dump.cs and whatever else: only the DLLs are kept
            if extra.name != "DummyDll":
                extra.unlink() if extra.is_file() else shutil.rmtree(extra, ignore_errors=True)
        final = root / key
        shutil.rmtree(final, ignore_errors=True)
        work.rename(final)
        (final / _MARKER).write_text(json.dumps({
            "binary": str(inputs.binary), "metadata": str(inputs.metadata), "tool_revision": TOOL_REVISION,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"), "dll_count": len(dlls),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        # folder_path: the GUI log turns that path into a link that opens the folder (main_log_pane._on_log_record)
        # debug only: the GUI switches the game right after and logs ONE line for both («Скрипты IL2CPP читаются по
        # подготовленным DLL: <link>», install_prepared_generator) — the user found two lines one too many
        logger.debug("Подготовлены DLL скриптов IL2CPP (%d): %s", len(dlls), final / "DummyDll",
                     extra={"folder_path": str(final / "DummyDll")})
        return final / "DummyDll"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _run(exe: Path, binary: Path, inputs: Il2CppInputs, out_dir: Path, should_cancel, on_line, timeout_s) -> str:
    """Runs the process, collecting its output; polls should_cancel and the timeout. Returns the whole output."""
    proc = subprocess.Popen(
        [str(exe), str(binary), str(inputs.metadata), str(out_dir)],
        cwd=str(inputs.work_dir), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=_CREATE_NO_WINDOW)
    lines: List[str] = []

    def pump():
        for raw in proc.stdout:
            # .NET Framework writes redirected console output in the OEM code page (exception texts are localized)
            line = raw.decode("oem" if os.name == "nt" else "utf-8", errors="replace").rstrip("\r\n")
            lines.append(line)
            if on_line is not None:
                try:
                    on_line(line)
                except Exception:   # noqa: BLE001 - a progress callback must not break the run
                    pass

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    started = time.monotonic()
    try:
        while proc.poll() is None:
            if should_cancel():
                raise DumperCancelled()
            if time.monotonic() - started > timeout_s:
                raise DumperError(tr("Подготовка скриптов заняла слишком много времени и была остановлена."),
                                  details="\n".join(lines[-60:]))
            time.sleep(0.2)
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    finally:
        reader.join(timeout=5)
    output = "\n".join(lines)
    logger.debug("Il2CppDumper завершился (код %s):\n%s", proc.returncode, output[-4000:])
    return output
