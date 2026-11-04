"""PyQt-free video transcode/probe logic for VideoClip converted import,
wrapping this project's own vendored, minimal ffmpeg.exe/ffprobe.exe (see
minimal_ffmpeg/ at the project root for the build setup, and CLAUDE.md's
ffmpeg section for the full design discussion behind the choices below).

Only two encode targets exist — deliberately matching Unity's own
VideoClipImporter, which only ever transcodes into H.264, H.265, or VP8
(confirmed against Unity's own docs, not assumed). H.265 was deliberately
left out: Windows' own hevc_mf encoder isn't guaranteed present on every
end-user machine (a separate, sometimes-paid "HEVC Video Extensions"
package), and libx265 (the guaranteed alternative) is GPL and comparatively
large for a codec that isn't load-bearing for playability, only for smaller
files at equal quality. What's left is genuinely free either way:
  - "h264": H.264 via Windows' own Media Foundation (h264_mf) + AAC (aac_mf)
    into an .mp4 — the same underlying codec libraries PyQt6's own bundled
    Qt6Multimedia backend already ships for playback.
  - "vp8": VP8 via libvpx + Vorbis via libvorbis into a .webm — Unity pairs
    VP8 with Vorbis audio, not AAC.
Both paths are LGPL-only, no GPL code anywhere in this project's own
vendored ffmpeg build.
"""

from core.i18n import tr
import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

from .progress import OperationCancelled

# Real, confirmed bug found testing the actual built CLI exe (1.1.0), not just
# the plain Python script: --video-transcode failed outright with "ffmpeg/
# ffprobe not found", even though cli_onefile_dlls.nuitka-package.config.yml
# already has a correctly-written UnityPy.resources.ffmpeg entry. Root-caused
# by reproducing it in an isolated, minimal Nuitka --onefile build (a tiny
# throwaway package with the identical shape — a resource-only submodule with
# an empty __init__.py, referenced only via a YAML module-name entry, never a
# real Python import): Nuitka's package-config DLL-bundling plugin only
# processes a module-name entry for a module it has ALREADY decided is part
# of the compiled program's own import graph — a module that exists ONLY as a
# YAML config target, with no corresponding `import` anywhere in the actual
# source, is never "discovered" and its dll config never fires, REGARDLESS of
# how correctly that entry is written. Confirmed directly: the same minimal
# repro's DLL/EXE files were silently absent from the onefile build's dist
# folder until an explicit `import` of that exact submodule was added, at
# which point they were correctly included. video_transcode.py resolves
# FFMPEG_EXE/FFPROBE_EXE via pure filesystem math relative to __file__ (this
# project's own established pattern for exactly this reason — see
# Fsb5Encoder.py's own docstring on why importlib.resources broke the same
# way under Nuitka), so this import's only purpose is to make Nuitka trace
# the submodule; nothing in this file ever uses the imported name itself.
# UnityPy.resources.bcn_encoder/fsb5_converter have the identical gap for the
# identical reason — fixed alongside this one, not left half-done.
import UnityPy.resources.ffmpeg  # noqa: F401

_RESOURCE_DIR = Path(__file__).resolve().parent.parent / "UnityPy" / "resources" / "ffmpeg"
FFMPEG_EXE = _RESOURCE_DIR / "ffmpeg.exe"
FFPROBE_EXE = _RESOURCE_DIR / "ffprobe.exe"

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# codec_name values as ffprobe itself reports them (confirmed against a real
# ffprobe run against this project's own vendored build, not guessed) —
# used both to pick the actual -c:v/-c:a encoder to invoke and to recognize
# when an input file's OWN codec already matches (see _input_matches_target).
TRANSCODE_TARGETS = {
    "h264": {
        "label": "H.264 (MP4 + AAC)",
        "container_ext": ".mp4",
        "video_encoder": "h264_mf",
        "audio_encoder": "aac_mf",
        "video_codec_names": {"h264"},
        "audio_codec_names": {"aac"},
        # VideoClip.m_Format — the ONE field a transcoded/converted import
        # never used to update at all (a real, confirmed bug: neither UnityPy's
        # own generated stub nor AssetStudio's C# source document this int
        # field's meaning, and this project deliberately never guessed it —
        # see probe_video_mismatch_warning()'s own comment). Empirically
        # confirmed, not guessed: a real, unmodified .mp4 VideoClip
        # (Phonopolis's own tutor_init, Unity 2022.3f2) declares m_Format=1;
        # a real .webm one (same fixture/version, tutor_chuze_mys) declares
        # m_Format=4. Causally verified against an ACTUAL running game (PUSS!,
        # also 2022.3f2): packing real H.264/MP4 bytes while m_Format stayed
        # at its old webm-era value (4) froze on a black screen; correcting
        # it to 1 made the video play correctly, with every other field held
        # identical between those two tests. This is the strongest possible
        # confirmation this project's own methodology asks for (a real
        # fixture AND a real causal test), stronger than a found-online
        # reference would have been.
        "m_format": 1,
    },
    "vp8": {
        "label": "VP8 (WebM + Vorbis)",
        "container_ext": ".webm",
        "video_encoder": "libvpx",
        "audio_encoder": "libvorbis",
        "video_codec_names": {"vp8"},
        "audio_codec_names": {"vorbis"},
        "m_format": 4,
    },
}


def is_available() -> bool:
    return FFMPEG_EXE.is_file() and FFPROBE_EXE.is_file()


def target_for_container_ext(ext: str) -> Optional[str]:
    """Maps a container extension (e.g. ".mp4") back to whichever
    TRANSCODE_TARGETS key produces it, if any. Used by the converted-import
    settings dialog to pre-select the transcode format matching a VideoClip's
    OWN current container (the format label shown in the Preview tab) instead
    of blindly defaulting to whatever format was picked last time — a real
    request: the dialog forced the user to notice and manually re-pick a
    format that was often already obvious from what's on screen. Returns None
    for an extension no target here produces (e.g. ".m4v"/".mkv"/".mov" —
    packageable, but not one of this project's own transcode outputs), so the
    caller can fall back to its own last-remembered choice."""
    ext = ext.lower()
    for key, target in TRANSCODE_TARGETS.items():
        if target["container_ext"].lower() == ext:
            return key
    return None


def probe(path) -> Optional[dict]:
    """Runs ffprobe -show_streams -show_format -of json on `path`, returns the
    parsed dict, or None on any failure (missing binary, bad/missing file,
    timeout, malformed output). Callers always treat None as "couldn't tell,
    don't try to be clever" rather than raising — every use of this is a
    non-fatal decision (the -c copy shortcut below, or a pre-flight
    compatibility warning), never a hard requirement for the import to
    proceed. See _probe_diag() for a variant that also reports WHY."""
    result, _reason = _probe_diag(path)
    return result


def _probe_diag(path) -> Tuple[Optional[dict], Optional[str]]:
    """Same as probe(), but also returns a human-readable reason string when
    it fails (None on success) — real reported bug this exists to
    investigate: a user-reported ffprobe failure on a real file that could
    not be reproduced through several different direct/isolated repro
    attempts (the same file, the same object, the same full MatchedPatch/
    apply_matched_patch chain, all succeeded when tried directly) — meaning
    whatever is actually failing in the live app is failing for a reason
    plain `probe()`'s bare None return can't distinguish (wrong exit code?
    stderr saying what? a timeout? an OSError launching the process at
    all?). transcode_video()'s own error message uses this instead of
    probe() specifically so the NEXT occurrence is actually diagnosable
    instead of another dead end."""
    if not FFPROBE_EXE.is_file():
        return None, tr("ffprobe.exe не найден по пути {ffprobe_exe}", ffprobe_exe=FFPROBE_EXE)
    try:
        result = subprocess.run(
            [str(FFPROBE_EXE), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30, creationflags=_CREATE_NO_WINDOW,
        )
    except OSError as e:
        return None, tr("не удалось запустить ffprobe.exe: {name}: {error}", name=type(e).__name__, error=e)
    except subprocess.TimeoutExpired:
        return None, tr("ffprobe.exe не завершился за отведённое время (30 сек)")
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        return None, tr("ffprobe.exe завершился с кодом {returncode}: {value}", returncode=result.returncode, value=stderr[:1000])
    try:
        return json.loads(result.stdout), None
    except json.JSONDecodeError as e:
        stdout_preview = (result.stdout or "")[:500]
        return None, tr("не удалось разобрать JSON-вывод ffprobe.exe: {error} (начало вывода: {stdout_preview!r})", error=e, stdout_preview=stdout_preview)


def _parse_rational(value: Optional[str]) -> Optional[float]:
    if not value or "/" not in value:
        return None
    num, den = value.split("/", 1)
    try:
        num_f, den_f = float(num), float(den)
    except ValueError:
        return None
    return num_f / den_f if den_f else None


def _input_matches_target(probe_result: dict, target_key: str) -> bool:
    """True only when the INPUT FILE's own freshly-probed codecs already
    match target_key's codec set exactly — deliberately compares against
    THIS probe result alone, never anything about the VideoClip object being
    imported into (its own declared width/height/etc. could already be
    stale from an earlier raw-packaging import that never touched them — a
    real, raised concern, not a hypothetical one). A True result just means
    ffmpeg's own `-c copy` (a real stream remux, not a guess) is safe to use
    instead of a full re-encode — it says nothing about whether the file
    will play correctly in Unity beyond "it's already in the exact codec
    this app would have produced anyway"."""
    target = TRANSCODE_TARGETS[target_key]
    streams = probe_result.get("streams", [])
    video_ok = any(
        s.get("codec_type") == "video" and s.get("codec_name") in target["video_codec_names"]
        for s in streams
    )
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    audio_ok = (not audio_streams) or any(
        s.get("codec_name") in target["audio_codec_names"] for s in audio_streams
    )
    return video_ok and audio_ok


def _video_quality_args(target_key: str, quality: int) -> list:
    """quality is a 0-100 UI scale (0 = normal/fastest, 100 = best/slowest) —
    same convention as the existing FSBank audio-quality slider. Mapped onto
    whatever quality knob each target's actual encoder exposes (confirmed
    via `ffmpeg -h encoder=...` against this project's own vendored build,
    not assumed): h264_mf has a direct 0-100 "-quality" option under its own
    "quality" rate-control mode; libvpx (VP8) has no such direct scale, only
    an inverted 0-63 "-crf" (lower = better) used with -b:v 0 for pure
    constant-quality mode (the standard libvpx recipe, not a guess)."""
    quality = max(0, min(100, quality))
    if target_key == "h264":
        return ["-rate_control", "quality", "-quality", str(quality)]
    if target_key == "vp8":
        crf = round(63 - (quality / 100.0) * 63)
        return ["-b:v", "0", "-crf", str(crf)]
    return []


def _audio_encode_args(target_key: str) -> list:
    """Deliberately NOT driven by the same quality slider as the video side —
    aac_mf exposes no quality/VBR knob at all (confirmed via `-h
    encoder=aac_mf`, bitrate-only), and a second, separate audio-quality
    control would be more UI than this feature's actual value justifies.
    Fixed, solid defaults instead: 192kbps AAC (a common, clearly-adequate
    bitrate for game audio) and libvorbis's own standard -q:a VBR scale at a
    comparable "high" quality point."""
    if target_key == "h264":
        return ["-b:a", "192k"]
    if target_key == "vp8":
        return ["-q:a", "6"]
    return []


def _read_last_out_time_seconds(progress_path: str) -> float:
    """ffmpeg's `-progress <file>` writes repeated blocks of key=value
    lines, appending as it goes — reading the whole (still small) file each
    poll and taking the LAST out_time_ms= line tolerates a partial write
    mid-block (an incomplete final line is simply not the last COMPLETE
    one)."""
    try:
        with open(progress_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except OSError:
        return 0.0
    last = 0.0
    for line in content.splitlines():
        if line.startswith("out_time_ms="):
            try:
                last = int(line.split("=", 1)[1]) / 1_000_000.0
            except ValueError:
                pass
    return last


@dataclass
class TranscodeResult:
    output_path: Path
    used_copy: bool  # True if ffmpeg's own `-c copy` remux was used instead of a real re-encode
    width: Optional[int]
    height: Optional[int]
    frame_rate: Optional[float]
    duration: Optional[float]


def transcode_video(
    input_path, output_path, target_key: str, quality: int = 70, *,
    progress_callback: Optional[Callable[[float, float, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> TranscodeResult:
    """Transcodes (or, when the input already matches, cheaply remuxes)
    `input_path` into `output_path` per `target_key` ("h264" or "vp8" — see
    TRANSCODE_TARGETS), then re-probes the ACTUAL output file to confirm it
    really decodes and to report its real width/height/frame_rate/duration —
    the caller (import_object_converted's VideoClip branch) uses these to
    write the VideoClip object's own metadata fields, so a transcoded import
    never leaves them stale the way plain raw-packaging does (a real,
    raised concern: an object's declared dimensions can already be wrong
    from an earlier untranscoded import, and this feature must never
    compound that by trusting anything about the OBJECT rather than the
    file actually being produced).

    progress_callback(current_seconds, total_seconds, phase) and
    should_cancel() use the exact same calling convention as
    task_queue.TaskFn's own report_progress/should_cancel — this function is
    meant to be called from inside one of those queued task fn()s, with
    both passed straight through with no adapter needed.

    Raises RuntimeError on any failure (missing binaries, ffmpeg itself
    failing, output not verifiable), core.progress.OperationCancelled if
    should_cancel() fires — never returns a "failed" result silently."""
    if not is_available():
        raise RuntimeError(tr("ffmpeg/ffprobe не найдены в {resource_dir} — переустановите приложение.", resource_dir=_RESOURCE_DIR))
    if target_key not in TRANSCODE_TARGETS:
        raise RuntimeError(tr("Неизвестный целевой формат транскодирования: {target_key}", target_key=target_key))

    target = TRANSCODE_TARGETS[target_key]
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    input_probe, probe_error = _probe_diag(input_path)
    if input_probe is None:
        raise RuntimeError(
            tr("Не удалось прочитать входной файл через ffprobe: {input_path}{value}", input_path=input_path, value=f' ({probe_error})' if probe_error else '')
        )
    if not any(s.get("codec_type") == "video" for s in input_probe.get("streams", [])):
        raise RuntimeError(tr("Во входном файле не найдена видеодорожка."))

    used_copy = _input_matches_target(input_probe, target_key)
    try:
        total_duration = float(input_probe.get("format", {}).get("duration", 0.0) or 0.0)
    except (TypeError, ValueError):
        total_duration = 0.0

    fd, progress_path = tempfile.mkstemp(prefix="ustudio_ffmpeg_progress_", suffix=".txt")
    os.close(fd)

    args = [str(FFMPEG_EXE), "-y", "-hide_banner", "-v", "error",
            "-progress", progress_path, "-nostats",
            "-i", str(input_path)]
    if used_copy:
        args += ["-c", "copy"]
    else:
        args += ["-c:v", target["video_encoder"], *_video_quality_args(target_key, quality),
                  "-c:a", target["audio_encoder"], *_audio_encode_args(target_key)]
    args += [str(output_path)]

    phase = tr("Копирование потоков") if used_copy else tr("Транскодирование видео")

    try:
        proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            creationflags=_CREATE_NO_WINDOW,
        )
    except OSError as e:
        raise RuntimeError(tr("Не удалось запустить ffmpeg: {error}", error=e))

    try:
        while True:
            if should_cancel is not None and should_cancel():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                # Always remove whatever output exists, even a fully-written
                # one — a short/fast encode can race should_cancel() and
                # finish before terminate() has any effect (confirmed via a
                # real test: a ~2s clip completed before a "cancel on the
                # 2nd poll" check fired, terminate() on the already-exited
                # process was a no-op, and the finished file survived).
                # Cancelled must mean cancelled regardless of that timing —
                # leaving a stray finished file around from a "cancelled"
                # task would contradict the status the queue reports.
                try:
                    os.remove(output_path)
                except OSError:
                    pass
                raise OperationCancelled()
            ret = proc.poll()
            if progress_callback is not None and total_duration > 0:
                current = min(_read_last_out_time_seconds(progress_path), total_duration)
                # Whole seconds, not this project's usual raw item counts —
                # real reported complaint: task_queue's shared row/header
                # widgets format progress_current/progress_total as plain
                # numbers (":," thousands-separated for the header, a bare
                # "current/total" for each row), which is the right call for
                # every OTHER task here (genuine object/file counts) but
                # rendered this task's real seconds.duration=118.315782 with
                # 6 decimal places and no unit anywhere — confusing on its
                # own, and actively misleading in the header's "всего" cell,
                # which reads as an ITEM COUNT for every other task kind.
                # Rounding to whole seconds won't fully resolve the "what do
                # these numbers mean" question (that's addressed by putting
                # "(транскодирование)" in the task's own title instead, see
                # object_actions.py), but at least stops the decimal-laden
                # noise.
                progress_callback(round(current), round(total_duration), phase)
            if ret is not None:
                break
            time.sleep(0.2)

        stderr_output = proc.stderr.read() if proc.stderr else ""
        if proc.returncode != 0:
            raise RuntimeError(
                tr("ffmpeg завершился с ошибкой (код {returncode}): {value}", returncode=proc.returncode, value=stderr_output.strip()[:2000])
            )
        if progress_callback is not None and total_duration > 0:
            progress_callback(round(total_duration), round(total_duration), phase)
    finally:
        try:
            os.remove(progress_path)
        except OSError:
            pass

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError(tr("ffmpeg завершился без ошибок, но результирующий файл не был создан."))

    output_probe = probe(output_path)
    if output_probe is None:
        raise RuntimeError(tr("Результат транскодирования не удалось проверить через ffprobe (файл повреждён?)."))
    video_stream = next((s for s in output_probe.get("streams", []) if s.get("codec_type") == "video"), None)
    if video_stream is None:
        raise RuntimeError(tr("В результирующем файле не найдена видеодорожка."))

    try:
        out_duration = float(output_probe.get("format", {}).get("duration", 0.0) or 0.0)
    except (TypeError, ValueError):
        out_duration = None

    return TranscodeResult(
        output_path=output_path,
        used_copy=used_copy,
        width=video_stream.get("width"),
        height=video_stream.get("height"),
        frame_rate=_parse_rational(video_stream.get("r_frame_rate")),
        duration=out_duration or None,
    )
