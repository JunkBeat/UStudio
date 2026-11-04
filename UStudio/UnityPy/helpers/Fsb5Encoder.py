"""WAV -> FSB5 encoding for AudioClip converted-import, via a vendored,
prebuilt `FSB5.Converter.exe` — a thin CLI wrapper (source provided for
inspection, not built by this project's own setup.py) around FMOD's own
official FSBank library (`fsbank.dll`/`fmod.dll` etc., vendored alongside the
exe under UnityPy/resources/fsb5_converter/, same convention as
UnityPyBoost's prebuilt .pyd and BcnEncoder's DLLs elsewhere in this
project). Subprocess-based, unlike the CLR-based texture path, since FSBank
has no direct Python binding here (only the read-side `fmod_toolkit`
dependency, itself a pyfmodex/FMOD Core wrapper for DECODING, does).

Investigated before writing anything new, per an explicit request not to
invent unnecessary logic if the existing tooling is already good enough: this
IS the existing tooling (the user's own `FSB5.Converter-main` source, itself
a thin wrapper around FMOD's OFFICIAL FSBank C API — `FSBank_Init`/
`FSBank_Build`), so there was nothing to reimplement; it's already reliable
by construction (it's Firelight's own encoder, not a from-scratch FSB5
muxer). The prebuilt exe that shipped with that source was a DEBUG build
(msvcp140d.dll/ucrtbased.dll/fmodL.dll — the "d"-suffixed debug CRT/FMOD
variants, which need the debug redistributable most end-user machines don't
have and are noticeably slower) — rebuilt in Release|x64 from the same
source with this project's own MSVC Build Tools install (see CLAUDE.md's
"dev_scripts/build_unitypyboost.py" section for that toolchain) instead of
vendoring the debug build as-is.

FSBank's own native format enum (fsbank.h's FSBANK_FORMAT: PCM, XMA, AT9,
Vorbis, FADPCM, OPUS — no MP3, no ADPCM member at all) is a HARD capability
ceiling, not a to-do list this wrapper is merely incomplete against: Unity's
AudioCompressionFormat.MP3/.ADPCM/.GCADPCM simply cannot be reproduced via
FSBank regardless of how this wrapper is written. Only PCM and Vorbis have an
unambiguous, verified 1:1 name match against both enums — see
_COMPRESSION_FORMAT_TO_FSBANK below for the full reasoning on why the rest
(XMA/AT9/AAC/VAG/HEVAG, plus ADPCM/MP3/GCADPCM) are deliberately out of scope
for AudioClip converted-import rather than guessed at.
"""

import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Optional

_LOCK = threading.Lock()
# Real bug found running the Nuitka --standalone build (ModuleNotFoundError:
# No module named 'UnityPy.resources.fsb5_converter'): importlib.resources.
# files(package) resolves its argument via importlib.import_module(package)
# under the hood — Nuitka's static import-follower has no way to see that
# indirection (the package name only ever exists as this module-level string,
# never a literal `import UnityPy.resources.fsb5_converter` anywhere), so it
# never registers that submodule as importable in the frozen build, even
# though --include-package-data=UnityPy DOES correctly copy the actual DLL
# files to disk — the files are physically present, only the "import this
# folder as a module to locate it" step was the part that broke. Resolving
# the path directly relative to this file's own location sidesteps the
# import system entirely (pure filesystem math, no module lookup), so it
# works identically whether this file is a normal .py, frozen by Nuitka, or
# anything else — confirmed by re-running an unmodified normal Python session
# after this change with no behavior difference. Same fix applied to
# BcnEncoder.py's identical pattern (found via grep, not guessed) for the
# same reason — it wasn't reported yet, but it is exactly the same bug.
#
# Second, SEPARATE real bug found later, testing the actual built CLI exe
# (1.1.0) in --onefile mode specifically, not just --standalone: even with
# the fix above (no more importlib.resources indirection), cli_onefile_dlls.
# nuitka-package.config.yml's own UnityPy.resources.fsb5_converter DLL entry
# still never fired — the actual fmod/fsbank/FSB5.Converter.exe files were
# silently absent from the onefile build. Root-caused via an isolated minimal
# --onefile repro with the identical shape (a resource-only submodule, empty
# __init__.py, referenced only via a YAML module-name entry, never a real
# Python import): Nuitka's package-config DLL-bundling plugin only processes
# an entry for a module it has ALREADY decided is part of the compiled
# program's own import graph — existing purely as a YAML target with no
# corresponding `import` anywhere is never "discovered", so the entry never
# fires, regardless of how correctly it's written. Confirmed directly: the
# repro's DLL/EXE files appeared in the onefile dist folder only once an
# explicit `import` of that exact submodule was added. video_transcode.py's
# UnityPy.resources.ffmpeg has the identical gap for the identical reason —
# fixed alongside this one, not left half-done.
import UnityPy.resources.fsb5_converter  # noqa: F401

_RESOURCE_DIR = Path(__file__).resolve().parent.parent / "resources" / "fsb5_converter"
_EXE_NAME = "FSB5.Converter.exe"


def ensure_fmod_dll_override() -> None:
    """Points `fmod_toolkit`/`pyfmodex` (the library UnityPy's own
    AudioClipConverter uses to DECODE AudioClips for export/preview) at the
    SAME fmod.dll this module's FSBank encoder is built against, instead of
    fmod_toolkit's own bundled copy — closing a real, measured FMOD version
    gap rather than merely working around it.

    Real, confirmed-not-guessed finding: fmod_toolkit ships FMOD 2.0.22;
    FSBank here is FMOD 2.2.17. A freshly-FSBank-encoded FSB5 failed to
    decode through fmod_toolkit's bundled 2.0.22 (`FmodError: INVALID
    PARAM`) but opened without error through FSBank's own 2.2.17 — proving
    this is a genuine encoder/decoder version gap, not a malformed FSB5 or a
    bug in this wrapper's arguments. `pyfmodex.fmodex` (site-packages/
    pyfmodex/fmodex.py) already has an official override for exactly this: it
    checks the `PYFMODEX_DLL_PATH` env var BEFORE falling back to
    fmod_toolkit's bundled DLL — no monkeypatching of the installed package
    needed. FMOD's own Core API is designed to be forward-compatible (a newer
    runtime reading older content is the standard, well-supported direction;
    only the reverse — an old runtime opening newer-format content — is
    expected to fail, matching exactly what was measured here), so pointing
    the WHOLE app's decode path at the newer, already-vendored fmod.dll is a
    real fix, not just a hedge — verified directly against a real fixture
    (Petscop): 15/15 sampled EXISTING AudioClips (a mix of Vorbis, real game
    audio, not synthetic) still decoded correctly under the override, and a
    freshly-FSBank-encoded FSB5 that failed under the old DLL decoded
    correctly too.

    Must run before the FIRST `import fmod_toolkit`/`import pyfmodex`
    anywhere in the process — module-level code in pyfmodex.fmodex reads the
    env var exactly once. Both AudioClipConverter.py and this module's own
    verify_decodable() call this before importing fmod_toolkit, so whichever
    runs first wins (idempotent — a user-set PYFMODEX_DLL_PATH is never
    overwritten, checked via `setdefault`).

    The FMOD files are not part of the public source repository (FMOD's own
    licence): without fmod.dll here, fmod_toolkit's bundled copy is left in
    charge, which still decodes the games' existing audio."""
    fmod_dll = _RESOURCE_DIR / "fmod.dll"
    if fmod_dll.is_file():
        os.environ.setdefault("PYFMODEX_DLL_PATH", str(fmod_dll))


# FMOD's files the encoder needs next to FSB5.Converter.exe (not in the public repository).
_FMOD_FILES = ("fsbank.dll", "fmod.dll", "libfsbvorbis64.dll")


def missing_fmod_files() -> list:
    return [name for name in _FMOD_FILES if not (_RESOURCE_DIR / name).is_file()]

# Unity's AudioCompressionFormat (UnityPy/enums/Audio.py) -> FSBank's own
# FSBANK_FORMAT name (fsbank.h), used as this exe's `-f` argument. Only the
# two formats with an exact, unambiguous, hand-verified match are listed —
# see this module's own docstring for why ADPCM/MP3/GCADPCM cannot be added
# here at all (FSBank has no such native format), and XMA/AT9/AAC/VAG/HEVAG
# are real FSBank/native formats this tool COULD in principle target, but are
# platform-specific enough (console/mobile) that this Windows-targeted
# single-developer tool has no verified fixture to test against yet — left
# out rather than guessed at, per this project's own established methodology.
_COMPRESSION_FORMAT_TO_FSBANK = {
    "PCM": "PCM",
    "Vorbis": "Vorbis",
}


def supported_compression_formats():
    """Names from UnityPy.enums.Audio.AudioCompressionFormat this module can
    target — currently just PCM/Vorbis, see the module docstring."""
    return tuple(_COMPRESSION_FORMAT_TO_FSBANK.keys())


def _exe_path() -> str:
    return str(_RESOURCE_DIR / _EXE_NAME)


def encode_wav_to_fsb(wav_path: str, compression_format: str, quality: int = 0) -> bytes:
    """Encodes a WAV file into a single-subsound FSB5 bank matching
    `compression_format` (an AudioCompressionFormat NAME — "PCM"/"Vorbis",
    see supported_compression_formats()). `quality` is FSBank's own 0-100
    scale (0 = "normal", per the tool's own --help text) — passed straight
    through, no remapping.

    Returns the raw .fsb bytes. Raises RuntimeError on any failure (missing
    exe, FSBank error, ...) with the tool's own stderr/stdout folded in —
    this is a low-level primitive, the caller (import_object_converted's
    AudioClip branch) is what turns that into the project's usual Russian
    user-facing message.

    Runs the whole exe+temp-output-file dance under a lock: FSB5.Converter.exe
    takes an output FOLDER, not a file, and always writes "{name}.fsb" into
    it — running two encodes concurrently against the same temp folder could
    only ever race by chance (each call gets its own tempfile.TemporaryDirectory,
    so this isn't strictly needed for correctness), but FSBank's own C API
    documents an internal cache/thread-count model this project has not
    stress-tested for concurrent process-level invocations — serializing here
    costs nothing (imports are not a hot path) and avoids being the first to
    find out."""
    exe_path = _exe_path()
    if not os.path.isfile(exe_path):
        raise RuntimeError(f"FSB5.Converter.exe не найден по пути {exe_path} — переустановите приложение.")
    missing = missing_fmod_files()
    if missing:
        raise RuntimeError(
            f"Не найдены файлы FMOD ({', '.join(missing)}) в папке {_RESOURCE_DIR} — "
            "без них звук в формат FSB5 не кодируется."
        )

    fsbank_format = _COMPRESSION_FORMAT_TO_FSBANK.get(compression_format)
    if fsbank_format is None:
        raise RuntimeError(
            f'Формат сжатия "{compression_format}" не поддерживается конвертированным '
            f"импортом аудио (доступны: {', '.join(supported_compression_formats())})."
        )

    with _LOCK:
        with tempfile.TemporaryDirectory(prefix="ustudio_fsb5_") as tmp_dir:
            out_name = "encoded"
            cache_dir = os.path.join(tmp_dir, "cache")
            os.makedirs(cache_dir, exist_ok=True)
            args = [
                exe_path,
                "-a", str(wav_path),
                "-f", fsbank_format,
                "-n", out_name,
                "-o", tmp_dir,
                "-q", str(quality),
                "-c", cache_dir,
            ]
            try:
                result = subprocess.run(
                    args, capture_output=True, text=True, timeout=120,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(f"FSB5.Converter.exe не завершился за отведённое время: {e}")
            except OSError as e:
                raise RuntimeError(f"Не удалось запустить FSB5.Converter.exe: {e}")

            out_path = os.path.join(tmp_dir, f"{out_name}.fsb")
            if result.returncode != 0 or not os.path.isfile(out_path):
                detail = (result.stdout or "") + (result.stderr or "")
                raise RuntimeError(
                    f"FSB5.Converter.exe завершился с ошибкой (код {result.returncode}): {detail.strip()}"
                )
            with open(out_path, "rb") as f:
                return f.read()


def verify_decodable(fsb_bytes: bytes, channels: int, frequency: int) -> Optional[str]:
    """Sanity check: tries to open the encoded bytes through `fmod_toolkit`
    (the SAME library UnityPy's own AudioClipConverter uses to DECODE
    AudioClips for export/preview), returning None if it opens fine or a
    human-readable reason if it doesn't.

    Originally written as a "warn but don't block" hedge against a real,
    measured gap: fmod_toolkit ships FMOD 2.0.22 while FSBank here is FMOD
    2.2.17, and a freshly-encoded FSB5 failed to open under the older
    version. ensure_fmod_dll_override() (called below, and by
    AudioClipConverter.py before it ever imports fmod_toolkit) closes that
    gap directly by pointing fmod_toolkit at FSBank's own fmod.dll instead of
    its bundled one — verified end-to-end (see that function's own docstring)
    that this fixes the freshly-encoded case while leaving existing/older
    AudioClip decoding unaffected. This function still exists as a genuine
    safety net rather than being deleted: `PYFMODEX_DLL_PATH` can only be set
    ONCE per process, so if something else in the process imports
    fmod_toolkit before this module ever runs (a plugin, a future code path,
    an explicit user override of the env var), the old gap could still
    surface — in which case this still returns a message instead of the
    caller silently trusting an unverified encode."""
    ensure_fmod_dll_override()
    try:
        import fmod_toolkit
    except Exception as e:
        return f"не удалось загрузить fmod_toolkit для проверки: {e}"
    try:
        samples = fmod_toolkit.raw_to_wav(fsb_bytes, "verify", channels or 2, frequency or 44100)
        if not samples:
            return "проверка декодирования вернула пустой результат"
    except Exception as e:
        return f"{type(e).__name__}: {e}"
    return None
