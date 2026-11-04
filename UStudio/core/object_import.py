"""Import of an edited object: JSON, raw serialized bytes, converted (type-specific) and texture-array slices."""

from core.i18n import N_, tr
import json
import os
import re
import tempfile
import traceback
from pathlib import Path, PurePosixPath
from typing import Callable, List, Optional, Tuple
from UnityPy.enums.Audio import AudioCompressionFormat
from UnityPy.enums.TextureFormat import TextureFormat
from UnityPy.helpers import Fsb5Encoder
from . import video_transcode as _video_transcode
from .file_utils import format_size, safe_join
from .progress import OperationCancelled

from .object_common import IMPORT_WARNING_PREFIX, MAX_IMPORT_JSON_BYTES, _FULL_MIPMAP_CHAIN, _TEXTURE_QUALITY_TO_ENCODER, safe_parse_dict, write_error_reason
from .object_content_raw import import_object_content_raw
from .object_dump import _resolve_parsed_data
from .object_export import build_export_stem, restore_dict_from_json_edit
from .object_resources import _probe_video_file_metadata, peek_videoclip_ext, probe_video_mismatch_warning
from .object_sprite import import_sprite_converted
from .json_check import json_replacement_problem
from .raw_check import raw_replacement_problem


PARTIAL_PARSE_BLOCK_MESSAGE = (
    N_("Объект прочитан не полностью, поэтому запись через дерево типов небезопасна "
    "(данные могут быть испорчены). Используйте Raw-импорт.")
)


def partial_parse_block_reason(obj) -> Optional[str]:
    """Message if obj can't be safely REWRITTEN through its typetree, else None.
    Every non-raw import (JSON, converted, content-raw with an inline field, the
    edit dialog) ends in obj.patch()/save_typetree(), which serializes from the
    object's TypeTree schema. For an object that only PARTIALLY parses (the
    generator-built schema of an IL2CPP MonoBehaviour is wrong/incomplete) that
    schema does not match the real bytes, so the write raises (real report:
    KeyError 'm_GameObject') or, worse, could store a wrong layout. Raw import
    replaces bytes wholesale and stays allowed. Only MonoBehaviour is checked:
    other types use TPK schemas that parse fully, and parsing e.g. a large
    Texture2D just to find that out would be wasted work."""
    if getattr(obj.type, "name", "") != "MonoBehaviour":
        return None
    data, is_partial, _err = _resolve_parsed_data(obj)
    if data is None or is_partial:
        return tr(PARTIAL_PARSE_BLOCK_MESSAGE)
    return None


def _contains_omitted_bytes_note(value) -> bool:
    """True if a dump holds the "<bytes: N>" placeholder _to_jsonable() writes for a bytes
    field over the export cap (nothing to restore from it — importing would fail or worse)."""
    if isinstance(value, str):
        return value.startswith("<bytes: ")
    if isinstance(value, dict):
        # _to_jsonable()'s cut of a dict past max_list_items
        return "..." in value or any(_contains_omitted_bytes_note(v) for v in value.values())
    if isinstance(value, list):
        # ... and of a list: a Font's m_FontData over 2,000,000 items (Phonopolis, PUSS!) ends with this note
        # every language's text for it starts «... (» (tests/test_i18n.py holds the catalogs to that)
        if value and isinstance(value[-1], str) and value[-1].startswith("... ("):
            return True
        return any(_contains_omitted_bytes_note(v) for v in value if isinstance(v, (str, dict, list)))
    return False


def import_object_json(obj, json_path: Path) -> Optional[str]:
    """Patches obj from a JSON file (as produced by export_object's JSON fallback,
    or hand-edited) — the file-based counterpart to JsonEditorDialog's inline text
    edit, both ultimately calling obj.patch(). Returns an error message, or None on
    success."""
    blocked = partial_parse_block_reason(obj)
    if blocked:
        return blocked
    json_path = Path(json_path)
    try:
        size = json_path.stat().st_size
        if size > MAX_IMPORT_JSON_BYTES:
            return tr("Файл слишком большой ({size}); загрузка отменена.", size=format_size(size))
        # errors="surrogateescape" mirrors the write side (dump_single_object/
        # _export_one_item/export_object() all now encode with this same codec) —
        # without it, reading back a dump that legitimately contains a
        # surrogateescape-reproduced non-UTF8 byte (a binary-ish string field
        # too small/varied to have tripped the _looks_binary() marker-wrapping
        # above) would raise UnicodeDecodeError here instead of round-tripping.
        with open(json_path, "r", encoding="utf-8", errors="surrogateescape") as f:
            data = json.load(f)
    except Exception as e:
        return tr("Не удалось прочитать JSON: {error}", error=e)

    if not isinstance(data, dict):
        return tr("Корневой элемент JSON должен быть объектом.")

    # build_export_json()/build_preview_json() encode raw bytes fields via
    # _to_jsonable()'s {"__bytes_hex__": ...} marker (same one
    # prepare_dict_for_json_edit() uses for the Edit Data path) — decode it back
    # to real bytes before patch(), mirroring open_json_editor_dialog's
    # restore_dict_from_json_edit() call. Without this, patch() would pass a
    # plain hex string through to write_typetree() for a bytes-typed field,
    # which raises TypeError deep in EndianBinaryWriter.write() (confirmed
    # against the real write path).
    data = restore_dict_from_json_edit(data)

    if _contains_omitted_bytes_note(data):
        return (
            tr("В дампе большие двоичные поля (например, пиксели текстуры > 1 МБ) не сохранены — он не полный, "
               "поэтому импорт невозможен. Импортируйте Raw (.dump.bin) или конвертированный файл (например, "
               "PNG).")
        )

    # The dump must be this object's: its script and the very fields the object has (core/json_check.py).
    problem = json_replacement_problem(obj, data)
    if problem:
        return problem

    try:
        obj.patch(data)
    except Exception as e:
        return tr("Не удалось применить JSON: {write_error_reason}\n{format_exc}", write_error_reason=write_error_reason(e), format_exc=traceback.format_exc())
    return None


def export_object_raw(obj, output_dir: Path) -> Tuple[Optional[Path], Optional[str]]:
    """Writes obj.get_raw_data() to {stem}.dump.bin — a deliberate, always-available
    export choice, distinct from export_object()'s own ".raw.bin" fallback filename
    (still used only when a JSON dump fails to parse) to avoid the two colliding.
    Named to parallel ".dump.json" (the JSON-dump export) — same object, binary
    form instead of typetree-parsed form."""
    try:
        stem = build_export_stem(obj)
        out_path = safe_join(output_dir, f"{stem}.dump.bin")
        with open(out_path, "wb") as f:
            f.write(obj.get_raw_data())
        return out_path, None
    except Exception as e:
        return None, tr("Экспорт Raw не удался: {error}\n{format_exc}", error=e, format_exc=traceback.format_exc())


def import_object_raw(obj, file_path: Path) -> Optional[str]:
    """Replaces obj's own serialized bytes wholesale via set_raw_data() — a plain
    byte read + assignment, the same cost class as get_raw_data()'s existing reads
    elsewhere in this app (which already handle much larger real data with no size
    cap), so no artificial ceiling is applied here the way import_object_json's
    MAX_IMPORT_JSON_BYTES guards against a huge/wrong file reaching json.loads()."""
    file_path = Path(file_path)
    try:
        with open(file_path, "rb") as f:
            data = f.read()
    except Exception as e:
        return tr("Не удалось прочитать файл: {error}", error=e)
    # Replacing bytes wholesale is the one import nothing looks at afterwards: refuse what cannot be this
    # object's data (garbage, a cut-off dump, another script's data) instead of saving it — see core/raw_check.py.
    problem = raw_replacement_problem(obj, data)
    if problem:
        return problem
    try:
        obj.set_raw_data(data)
    except Exception as e:
        return tr("Не удалось применить Raw-данные: {write_error_reason}\n{format_exc}", write_error_reason=write_error_reason(e), format_exc=traceback.format_exc())
    return None


# Types with a real converted-import branch below — the single source of truth
# for whether "Импортировать из файла (с настройками)..." should even be
# offered for a given object (object_actions.py imports this set directly
# rather than hardcoding its own copy of the type list). Grows as Video/Sprite
# phases land (see ROADMAP.md) — Mesh/Shader are deliberately never added
# (see this section's own module docstring).
CONVERTED_IMPORT_SUPPORTED_TYPES = {"Texture2D", "Texture2DArray", "AudioClip", "VideoClip"}


# Curated list of (TextureFormat member name, family, display label) for the
# "Выбрать вручную" format picker — deliberately NOT every TextureFormat enum
# member. Two reasons a format is excluded rather than just "not gotten to
# yet": either this pipeline genuinely can't encode it at all (PVRTC, HDR
# formats — no library here supports them), or it needs a per-instance detail
# this flat list can't carry (ASTC's many block sizes; only the two most
# common are offered here for a picker meant to stay simple, not because
# others don't work — image_to_texture2d() itself already handles any ASTC
# block size). BC7 is NOT filtered out here for pre-Unity-5 objects — that
# gating happens where the dialog is built, since it needs the actual
# object's version, which this plain data list has no access to.
TEXTURE_MANUAL_FORMAT_OPTIONS = (
    ("RGBA32", "uncompressed", N_("RGBA32 (без сжатия, с альфа-каналом)")),
    ("RGB24", "uncompressed", N_("RGB24 (без сжатия, без альфа-канала)")),
    ("Alpha8", "uncompressed", N_("Alpha8 (только альфа-канал)")),
    ("DXT1", "bc", N_("DXT1 / BC1 (без альфа-канала)")),
    ("DXT3", "bc", "DXT3 / BC2"),
    ("DXT5", "bc", "DXT5 / BC3"),
    ("BC4", "bc", N_("BC4 (один канал)")),
    ("BC5", "bc", N_("BC5 (два канала)")),
    ("BC7", "bc", N_("BC7 (лучшее качество среди BC, только для Unity 5+)")),
    ("ETC_RGB4", "etc", N_("ETC1 (без альфа-канала)")),
    ("ETC2_RGB", "etc", "ETC2 RGB"),
    ("ETC2_RGBA8", "etc", "ETC2 RGBA"),
    ("ASTC_RGBA_4x4", "astc", N_("ASTC 4x4 (выше качество, меньше сжатие)")),
    ("ASTC_RGBA_8x8", "astc", N_("ASTC 8x8 (ниже качество, больше сжатие)")),
    ("ATC_RGB4", "atc", N_("ATC RGB4 (без альфа-канала)")),
    ("ATC_RGBA8", "atc", "ATC RGBA8"),
)


# Conservative, verified-safe subset of BuildTarget — platforms where BC/DXT
# is unambiguously the native compressed format. Used only to steer the
# manual-format picker's platform-mismatch WARNING (see
# texture_format_platform_warning below), never to silently pick or block a
# format — the user's own explicit choice always wins. Deliberately not
# exhaustive: StandaloneOSX/iOS/tvOS/Switch/WebGL are all genuinely ambiguous
# (can ship BC, ETC, or ASTC depending on the specific build) and are left out
# of BOTH directions of the warning rather than guessed at.
_DESKTOP_CONSOLE_PLATFORMS = {
    "StandaloneWindows", "StandaloneWindows64",
    "StandaloneLinux", "StandaloneLinux64", "StandaloneLinuxUniversal",
    "PS4", "XboxOne", "XBOX360", "WSAPlayer",
}


# Mobile-only compressed families — the reverse direction of the same check.
_MOBILE_ONLY_FAMILIES = {"etc", "atc"}


def texture_format_family(format_name: str) -> Optional[str]:
    for name, family, _label in TEXTURE_MANUAL_FORMAT_OPTIONS:
        if name == format_name:
            return family
    return None


def texture_format_platform_warning(format_name: str, platform) -> Optional[str]:
    """A soft, informational mismatch warning for the manual format picker —
    never a block. Only fires in the two directions this project has actually
    verified are near-universally true (a BC/DXT format on a phone/tablet, or
    a mobile-only format on desktop/console); every other platform (mobile
    GPUs vary too much to say anything confident) or family (uncompressed,
    ASTC — genuinely used on both desktop and mobile) gets no warning at all,
    since a wrong warning is worse than a missing one here."""
    family = texture_format_family(format_name)
    if family is None:
        return None
    platform_name = getattr(platform, "name", str(platform)) if platform is not None else ""

    if platform_name in _DESKTOP_CONSOLE_PLATFORMS and family in _MOBILE_ONLY_FAMILIES:
        return (
            tr("Формат \"{format_name}\" обычно используется на мобильных платформах, а не на {platform_name} — "
               "текстура может не отображаться в игре.", format_name=format_name, platform_name=platform_name)
        )
    if platform_name and platform_name not in _DESKTOP_CONSOLE_PLATFORMS and family == "bc":
        return (
            tr("Формат \"{format_name}\" (BC/DXT) обычно не поддерживается на платформе {platform_name} — "
               "текстура может не отображаться в игре.", format_name=format_name, platform_name=platform_name)
        )
    return None


def _resolve_texture_import_settings(
    quality_tier: str,
    current_format,
    format_mode: str,
    manual_format: Optional[str],
):
    """Maps quality tier + format mode to (target_format_override,
    encoder_quality). Format and quality are fully independent axes:
    "match_original" (default) always keeps the object's own current format;
    "manual" uses whatever the user explicitly picked
    (TEXTURE_MANUAL_FORMAT_OPTIONS) instead — no tier-driven auto-selection of
    format exists (a "by_quality" mode was tried and dropped: tying format
    choice to the quality tier through a hidden lookup table produced
    incoherent pairings, e.g. "medium" and "high" quality silently picking
    the identical format). Quality always just varies the BC encoder's
    quality knob for whichever format ends up chosen."""
    encoder_quality = _TEXTURE_QUALITY_TO_ENCODER.get(quality_tier, "best")
    if format_mode == "manual" and manual_format:
        target_format = getattr(TextureFormat, manual_format, current_format)
    else:
        target_format = current_format
    return target_format, encoder_quality


# Real reported bug: classify_import_mode() only ever looks at a file's
# EXTENSION, with no idea which OBJECT TYPE it's about to be imported into —
# every extension in _CONVERTED_SUFFIXES classifies as mode "converted"
# regardless of target type, so picking a .json file for an AudioClip target
# still correctly resolved to "converted" (.json genuinely IS a real
# converted-import extension, just for TextAsset) and then got handed
# straight to Fsb5Encoder as if it were a WAV file, with nothing in between
# to catch the mismatch. Checked once, centrally, rather than duplicated
# per-branch — every branch in import_object_converted() below already
# implicitly assumed its own extension; this makes that assumption an
# explicit, clearly-worded failure instead of an opaque one from whatever
# the wrong-format file happens to break first (PIL raising a cryptic decode
# error, an external FSBank process crashing outright, or — worst case, Font
# — nothing raising at all, silently writing the wrong bytes as font data).
# TextAsset is deliberately NOT in this table: it genuinely accepts any
# extension/content as valid text-or-binary payload (see its own branch's
# comment on surrogateescape) — there's no "wrong format" for it to guard
# against, matching how classify_import_mode()/export_object() already
# treat it as the flexible, no-restrictions type.
_CONVERTED_IMPORT_EXTENSIONS = {
    "Texture2D": (".png",),
    "Sprite": (".png",),
    "Font": (".ttf", ".otf"),
    "AudioClip": (".wav",),
    "VideoClip": (".mp4", ".webm"),
}


def _check_converted_import_extension(type_name: str, file_path: Path) -> Optional[str]:
    allowed = _CONVERTED_IMPORT_EXTENSIONS.get(type_name)
    if allowed is None:
        return None
    if file_path.suffix.lower() in allowed:
        return None
    return (
        tr("Файл \"{name}\" не подходит для конвертированного импорта в тип \"{type_name}\" (ожидается "
           "расширение: {join}).", name=file_path.name, type_name=type_name, join=', '.join(allowed))
    )


def import_object_converted(
    obj,
    file_path: Path,
    *,
    texture_quality: str = "high",
    texture_mipmaps: bool = False,
    texture_format_mode: str = "match_original",
    texture_manual_format: Optional[str] = None,
    audio_quality: int = 0,
    resource_target_mode: str = "original",
    resource_name: Optional[str] = None,
    backup_before_overwrite: bool = False,
    backup_keep_latest: Optional[int] = None,
    video_transcode: bool = False,
    video_transcode_target: str = "h264",
    video_transcode_quality: int = 70,
    video_transcode_output_path: Optional[str] = None,
    report_progress: Optional[Callable[..., None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Optional[str]:
    """texture_quality/texture_mipmaps/texture_format_mode/
    texture_manual_format only apply to Texture2D (see
    _resolve_texture_import_settings); audio_quality only applies to AudioClip
    (FSBank's own 0-100 scale, 0 = "normal" — passed straight through to
    Fsb5Encoder.encode_wav_to_fsb, no remapping). resource_target_mode/
    resource_name/backup_before_overwrite/backup_keep_latest apply to
    AudioClip/VideoClip, whose converted-import branches both store their
    result via import_object_content_raw() — see that function's own
    docstring, these are passed straight through unchanged. video_transcode/
    video_transcode_target/video_transcode_quality/
    video_transcode_output_path only apply to VideoClip — see the VideoClip
    branch below and video_transcode.transcode_video()'s own docstring;
    video_transcode defaults to False (plain packaging, unchanged from
    before this existed) since transcoding is deliberately never triggered
    by the silent "Импортировать из файла..." action, only via "...с
    настройками" — see object_actions.py's own comment on why this has no
    CONFIG-level default. report_progress/should_cancel use the exact
    task_queue.TaskFn calling convention and are only actually consulted by
    the VideoClip transcode path (every other branch here is fast enough not
    to need them) — safe to omit for a non-VideoClip import or a caller with
    no queue underneath it (tests, a plain script).

    Callers driving this from a UI should resolve CONFIG.texture_import_quality/
    texture_import_mipmaps/texture_import_format_mode/texture_import_manual_format/
    audio_import_quality/resource_target_mode/resource_name
    (and any per-import dialog override, including the video_transcode_* axes)
    themselves and pass the results in; this PyQt-free module can't read CONFIG
    directly (config.py itself imports RICH_PREVIEW_TYPES from here, so the
    reverse import would be circular)."""
    file_path = Path(file_path)
    type_name = obj.type.name

    # VideoClip's own (.mp4/.webm) allow-list exists to guard PLAIN packaging
    # (the input's raw bytes go into the object as-is, so its extension must
    # already be something Unity can play) — it doesn't apply once
    # video_transcode is on, since the whole point is accepting any input
    # ffmpeg can decode and re-encoding it into a known-safe target; only the
    # OUTPUT container (decided by video_transcode_target, not this file)
    # matters then. Found via a real test, not anticipated: exporting this
    # project's own VideoClip fixtures produces .m4v files, which this
    # allow-list correctly rejects for plain packaging but would have also
    # wrongly rejected as a transcode SOURCE.
    if not (type_name == "VideoClip" and video_transcode):
        ext_error = _check_converted_import_extension(type_name, file_path)
        if ext_error:
            return ext_error

    if type_name == "Texture2D":
        try:
            from PIL import Image as PILImage
            img = PILImage.open(file_path)
        except Exception as e:
            return tr("Не удалось открыть файл изображения: {error}", error=e)
        try:
            data = obj.parse_as_object()
            target_format, encoder_quality = _resolve_texture_import_settings(
                texture_quality, data.m_TextureFormat, texture_format_mode, texture_manual_format
            )
            mip_count = _FULL_MIPMAP_CHAIN if texture_mipmaps else 1
            data.set_image(img, target_format=target_format, mipmap_count=mip_count, quality=encoder_quality)
            data.save()
        except Exception as e:
            return tr("Не удалось импортировать текстуру: {error}\n{format_exc}", error=e, format_exc=traceback.format_exc())
        return None

    if type_name == "Font":
        try:
            with open(file_path, "rb") as f:
                font_bytes = f.read()
        except Exception as e:
            return tr("Не удалось прочитать файл шрифта: {error}", error=e)
        full, err = safe_parse_dict(obj)
        if full is None:
            return tr("Не удалось прочитать текущие данные объекта: {error}", error=err)
        full["m_FontData"] = font_bytes
        # This branch only ever receives a real .ttf/.otf (classify_import_mode's own
        # extension check) — a vector font, meant to be rendered dynamically at runtime.
        # A pre-existing legacy static/bitmap Font (baked character rectangles on its own
        # texture, m_ConvertCase >= 0 selecting an upper/lower-case bake) would otherwise
        # keep those stale rects pointing at a bitmap layout that has nothing to do with the
        # new font — Unity would either ignore the new data or render garbage. Clearing the
        # rects and switching to dynamic mode (m_ConvertCase = -2, confirmed against every
        # real dynamic Font sampled across several shipped games — Amanda 2, Deep Sleep,
        # Elevated Dread, Kindergarten 3: all -2 with empty m_CharacterRects) is what makes a
        # freshly imported font file actually render, matching how Unity's own dynamic Font
        # objects are always stored. Applied unconditionally, not just for a font detected as
        # bitmap — an already-dynamic Font has empty rects/-2 already, so this is a no-op for
        # it and does not lose anything.
        full["m_CharacterRects"] = []
        full["m_ConvertCase"] = -2
        try:
            obj.patch(full)
        except Exception as e:
            return tr("Не удалось применить данные шрифта: {write_error_reason}\n{format_exc}", write_error_reason=write_error_reason(e), format_exc=traceback.format_exc())
        return None

    if type_name == "AudioClip":
        try:
            data = obj.parse_as_object()
        except Exception as e:
            return tr("Не удалось прочитать текущие данные объекта: {error}\n{format_exc}", error=e, format_exc=traceback.format_exc())
        try:
            compression_name = AudioCompressionFormat(data.m_CompressionFormat).name
        except ValueError:
            compression_name = str(data.m_CompressionFormat)
        if compression_name not in Fsb5Encoder.supported_compression_formats():
            return (
                tr("Конвертированный импорт аудио пока поддерживает только форматы {join} — у этого объекта "
                   "\"{compression_name}\" (FSBank, на котором это построено, физически не умеет кодировать в "
                   "остальные форматы сжатия Unity — см. UnityPy/helpers/Fsb5Encoder.py). Используйте Raw или "
                   "Content Raw.", join=', '.join(Fsb5Encoder.supported_compression_formats()), compression_name=compression_name)
            )
        # m_AudioData (pre-Unity-5 inline storage) is deliberately out of scope —
        # see _INLINE_CONTENT_FIELD's own comment: that field's exact expected
        # byte layout for a *write* was never verified, unlike the modern
        # m_Resource-based path this reuses import_object_content_raw() for.
        if not getattr(data, "m_Resource", None) or not data.m_Resource.m_Source:
            return (
                tr("Конвертированный импорт аудио поддерживается только для современных AudioClip с внешним "
                   "ресурсом (m_Resource) — у этого объекта данные хранятся иначе (вероятно, старый формат до Unity "
                   "5).")
            )
        missing_fmod = Fsb5Encoder.missing_fmod_files()      # not in the public source repository
        if missing_fmod:
            return tr("Для импорта звука нужны файлы FMOD, которых нет в папке программы: {files}.",
                      files=", ".join(missing_fmod))
        try:
            fsb_bytes = Fsb5Encoder.encode_wav_to_fsb(str(file_path), compression_name, quality=audio_quality)
        except Exception as e:
            return tr("Не удалось закодировать аудио в FSB5: {error}", error=e)
        # Belt-and-suspenders, not the primary fix (see
        # Fsb5Encoder.ensure_fmod_dll_override's docstring — that already
        # closes the real FMOD-version gap between this encoder and the
        # decoder UStudio's own preview uses, for every AudioClip, not just
        # this one import). Kept here in case something already imported
        # fmod_toolkit earlier in the process with a different DLL. A
        # WARNING-prefixed non-None return is NOT an error — see
        # apply_matched_patch()/IMPORT_WARNING_PREFIX's own comment for how
        # callers distinguish it from a real failure.
        verify_error = Fsb5Encoder.verify_decodable(
            fsb_bytes, data.m_Channels or 2, data.m_Frequency or 44100
        )
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".fsb")
        try:
            with os.fdopen(tmp_fd, "wb") as f:
                f.write(fsb_bytes)
            error = import_object_content_raw(
                obj, Path(tmp_path),
                resource_target_mode=resource_target_mode,
                resource_name=resource_name,
                backup_before_overwrite=backup_before_overwrite,
                backup_keep_latest=backup_keep_latest,
            )
            if error:
                return error
            if verify_error:
                return (
                    IMPORT_WARNING_PREFIX + tr("импорт выполнен, но проверка декодирования не прошла ({verify_error}) — "
                                               "звук может не воспроизводиться в игре.", verify_error=verify_error)
                )
            return None
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    if type_name == "VideoClip":
        # Two shapes: plain packaging (video_transcode=False, the original
        # ROADMAP.md-scoped behavior — candidate file's raw bytes go
        # straight into the object's external resource, no encoder step at
        # all) or a real transcode first (video_transcode=True — only ever
        # requested explicitly via "...с настройками", never the silent
        # default). Either way the actual storage is still
        # import_object_content_raw() — transcoding just decides what file
        # gets handed to it.
        try:
            data = obj.parse_as_object()
        except Exception as e:
            return tr("Не удалось прочитать текущие данные объекта: {error}\n{format_exc}", error=e, format_exc=traceback.format_exc())

        transcode_result = None
        original_fallback_note = None
        if video_transcode:
            if not video_transcode_output_path:
                return tr("Транскодирование включено, но не указан путь для сохранения результата.")
            resolved_target = video_transcode_target
            if resolved_target == "original":
                # Reaches here unresolved only when the caller couldn't
                # resolve "Same as original" itself either — a bulk
                # selection with no single object to check against (see
                # ConvertedImportSettingsDialog's own accept()/
                # _resolve_final_video_target(), which handles the
                # single-object, interactive case before this ever runs), or
                # a caller with no dialog at all (the CLI). No GUI-safe way
                # to ask here, so resolve silently: match this object's own
                # current container when possible, else fall back to the
                # first real target and say so in the returned advisory
                # instead of just silently guessing.
                matched = _video_transcode.target_for_container_ext(peek_videoclip_ext(obj))
                if matched:
                    resolved_target = matched
                else:
                    resolved_target = next(iter(_video_transcode.TRANSCODE_TARGETS))
                    fallback_label = _video_transcode.TRANSCODE_TARGETS[resolved_target]["label"]
                    original_fallback_note = (
                        tr("оригинальный формат этого видео нельзя транскодировать напрямую — использован формат "
                           "«{fallback_label}» по умолчанию.", fallback_label=fallback_label)
                    )
            try:
                transcode_result = _video_transcode.transcode_video(
                    file_path, video_transcode_output_path, resolved_target,
                    video_transcode_quality, progress_callback=report_progress,
                    should_cancel=should_cancel,
                )
            except OperationCancelled:
                raise
            except Exception as e:
                return tr("Не удалось транскодировать видео: {error}", error=e)
            file_path = transcode_result.output_path

        # Skipped when a transcode just ran: it would compare the candidate
        # against the object's OWN width/height/frame_rate, which are about
        # to be overwritten below to match the transcode's real output
        # anyway — comparing against values already known to be replaced
        # would be comparing against the wrong thing, not a meaningful
        # sanity check.
        warning = None if transcode_result else probe_video_mismatch_warning(file_path, data.Width, data.Height, data.m_FrameRate)

        error = import_object_content_raw(
            obj, file_path,
            resource_target_mode=resource_target_mode,
            resource_name=resource_name,
            backup_before_overwrite=backup_before_overwrite,
            backup_keep_latest=backup_keep_latest,
        )
        if error:
            return error

        # read_videoclip_bytes()/export_object() guess the playable extension
        # from m_OriginalPath's own suffix (a Unity provenance field recording
        # the ORIGINAL developer's import-time file extension), never from the
        # actual bytes now stored — so without this, the Preview tab's played/
        # displayed format silently disagrees with reality the moment the real
        # content's container changes (a transcode to a different target, or
        # even plain packaging of a file with a different extension). Always
        # refresh it to whatever file's bytes were just packaged: the
        # transcode's real output container for a transcode, the picked file
        # otherwise — file_path already points at whichever one actually
        # applies, having been reassigned to transcode_result.output_path
        # above when a transcode ran.
        full = None
        new_ext = Path(file_path).suffix
        original_path_value = getattr(data, "m_OriginalPath", "") or ""
        if new_ext and Path(original_path_value).suffix.lower() != new_ext.lower():
            full, err = safe_parse_dict(obj)
            if full is None:
                return IMPORT_WARNING_PREFIX + tr("видео импортировано, но не удалось обновить путь исходного файла: {error}",
                                                  error=err)
            base = original_path_value or Path(file_path).name
            full["m_OriginalPath"] = str(PurePosixPath(base).with_suffix(new_ext))

        # Real safety measure, not an afterthought: whatever bytes just got
        # packaged, the object's own declared metadata must actually agree
        # with them afterward — leaving Width/Height/m_FrameRate/m_FrameCount
        # at their OLD values here is exactly the staleness this project
        # otherwise takes care to avoid. This used to only run for an actual
        # transcode (plain packaging left these fields untouched entirely) —
        # a real, reported complaint: probe_video_mismatch_warning() above
        # already reads a plain-packaging candidate's real width/height/fps
        # via ffprobe just to WARN about a mismatch, so there was never a
        # good reason to then leave the object's own fields at the
        # now-confirmed-wrong values instead of writing back what was
        # already known. A transcode's own real output (TranscodeResult,
        # re-probed after encoding) is authoritative when one ran; otherwise
        # the plain-packaging candidate itself is probed directly, since its
        # bytes go in completely unchanged. Either way, values come from
        # actually probing real content, never assumed from what was merely
        # requested — and a probe failure (network drive hiccup, an exotic
        # container ffprobe can't read at all) just leaves the metadata as
        # it already was, the same fallback this path always had.
        if transcode_result is not None:
            probed = {
                "width": transcode_result.width, "height": transcode_result.height,
                "frame_rate": transcode_result.frame_rate, "duration": transcode_result.duration,
            }
        else:
            probed = _probe_video_file_metadata(file_path)

        if probed is not None:
            if full is None:
                full, err = safe_parse_dict(obj)
                if full is None:
                    return IMPORT_WARNING_PREFIX + tr("видео импортировано, но не удалось обновить метаданные объекта: {error}",
                                                      error=err)
            if probed["width"] and probed["height"]:
                full["Width"] = probed["width"]
                full["Height"] = probed["height"]
            if probed["frame_rate"]:
                full["m_FrameRate"] = probed["frame_rate"]
                if probed["duration"]:
                    full["m_FrameCount"] = round(probed["duration"] * probed["frame_rate"])

        # VideoClip.m_Format — the ONE field a converted import never wrote
        # back at all until this was actually tested in a real running game.
        # Neither UnityPy's own generated stub nor AssetStudio's C# source
        # document this int field's meaning (see TRANSCODE_TARGETS's own
        # comment for how its two "m_format" values were confirmed — not
        # guessed: empirically, against three independent real, unmodified
        # fixtures, AND causally, against an actual game — packing real
        # content while this field stays wrong reproducibly froze on a black
        # screen; correcting it, with every other field held identical, made
        # it play). Known outright for a transcode (resolved_target IS one of
        # the two real targets). For plain packaging, derived from the
        # packaged file's own container extension, same as "Same as
        # original" resolution — currently ALWAYS resolves in practice,
        # since _CONVERTED_IMPORT_EXTENSIONS["VideoClip"] already restricts
        # plain packaging to exactly these two extensions (confirmed by
        # testing a third container directly: rejected earlier, before ever
        # reaching this code). Kept as a real guard anyway, not dead-code
        # paranoia: that allow-list has already been widened once before in
        # this project's history for an unrelated reason (transcode SOURCE
        # containers), and TRANSCODE_TARGETS/_CONVERTED_IMPORT_EXTENSIONS are
        # two independently-maintained constants with no shared enforcement
        # — a future widening of one without the other would silently leave
        # m_Format wrong again, exactly the bug just fixed here, without this
        # note.
        format_target_key = (
            resolved_target if transcode_result is not None
            else _video_transcode.target_for_container_ext(new_ext)
        )
        format_unknown_note = None
        if format_target_key is not None:
            if full is None:
                full, err = safe_parse_dict(obj)
                if full is None:
                    return IMPORT_WARNING_PREFIX + tr("видео импортировано, но не удалось обновить метаданные объекта: {error}",
                                                      error=err)
            full["m_Format"] = _video_transcode.TRANSCODE_TARGETS[format_target_key]["m_format"]
        elif new_ext:
            format_unknown_note = (
                tr("поле m_Format не удалось обновить под новое содержимое (для этого контейнера нет "
                   "подтверждённого значения) — объект может не воспроизводиться в игре.")
            )

        if full is not None:
            try:
                obj.patch(full)
            except Exception as e:
                return IMPORT_WARNING_PREFIX + tr("видео импортировано, но не удалось обновить метаданные объекта: {error}",
                                                  error=e)

        notes = [n for n in (warning, original_fallback_note, format_unknown_note) if n]
        if notes:
            return IMPORT_WARNING_PREFIX + tr("импорт выполнен, но {problems}", problems="; ".join(notes))
        return None

    if type_name == "Sprite":
        error = import_sprite_converted(obj, file_path, texture_quality=texture_quality)
        return error

    if type_name == "TextAsset":
        # newline="" mirrors export_object()'s TextAsset branch — see its own
        # comment for why: without it, Python's universal-newline translation
        # would silently mangle any embedded 0x0A byte in a ".bin"-detected
        # binary TextAsset, and this is the read-side half of that exact
        # round trip (export .bin/.json/.txt -> edit -> reimport here).
        try:
            with open(file_path, "r", encoding="utf-8", errors="surrogateescape", newline="") as f:
                text = f.read()
        except Exception as e:
            return tr("Не удалось прочитать текстовый файл: {error}", error=e)
        full, err = safe_parse_dict(obj)
        if full is None:
            return tr("Не удалось прочитать текущие данные объекта: {error}", error=err)
        full["m_Script"] = text
        try:
            obj.patch(full)
        except Exception as e:
            return tr("Не удалось применить текст: {write_error_reason}\n{format_exc}", write_error_reason=write_error_reason(e), format_exc=traceback.format_exc())
        return None

    return (
        tr("Для типа \"{type_name}\" нет конвертированного импорта (не существует обратного преобразования из "
           "этого формата) — используйте Raw или Json дамп.", type_name=type_name)
    )


# Matches export_object()'s own Texture2DArray naming ("{stem}_sliceNN.png")
# but tolerant of a renamed prefix — only the "_sliceNN.ext" suffix is
# actually load-bearing for re-matching a slice back to its array index.
_TEXTURE_ARRAY_SLICE_RE = re.compile(r"_slice(\d+)\.(png|jpg|jpeg|bmp|tga)$", re.IGNORECASE)


def import_texture_array_slices(
    obj,
    folder_path: Path,
    *,
    texture_quality: str = "high",
    texture_mipmaps: bool = False,
) -> Tuple[Optional[str], int, int]:
    """Folder-based counterpart to import_object_converted() for
    Texture2DArray — that function takes one file, this takes a whole folder
    of slices. Returns (error, matched_count, depth): error is None on
    success (matched_count may still be less than depth — see below, that's
    not a failure).

    Implements the resolved "individual slices vs. strictly all slices
    together" question (see ROADMAP.md/CLAUDE.md): a folder need not contain
    every slice. Any index with no matching file in the folder keeps that
    slice's CURRENT compressed bytes untouched — byte-for-byte, no decode/
    recompress round trip (see Texture2DArray.set_images()'s own docstring) —
    so replacing one slice out of many costs nothing on the rest. Format is
    always match-original (set_images() explains why a manual target format
    isn't offered here); only texture_quality/texture_mipmaps apply, and
    texture_mipmaps is accepted for signature symmetry with the Texture2D
    path but currently has no effect — set_images() does not build a mip
    chain (matches Texture2DArray.images' own single-mip-level assumption)."""
    type_name = obj.type.name
    if type_name != "Texture2DArray":
        return tr("Ожидался тип Texture2DArray, получен \"{type_name}\".", type_name=type_name), 0, 0

    try:
        data = obj.parse_as_object()
    except Exception as e:
        return tr("Не удалось прочитать текущие данные объекта: {error}\n{format_exc}", error=e, format_exc=traceback.format_exc()), 0, 0

    depth = data.m_Depth
    slices: List[Optional[str]] = [None] * depth
    matched = 0
    for entry in Path(folder_path).iterdir():
        if not entry.is_file():
            continue
        m = _TEXTURE_ARRAY_SLICE_RE.search(entry.name)
        if not m:
            continue
        idx = int(m.group(1))
        if idx >= depth:
            continue  # out-of-range index — silently ignored, same as an unrelated file
        slices[idx] = str(entry)
        matched += 1

    if matched == 0:
        return (
            tr("В выбранной папке не найдено файлов среза (ожидается имя вида \"..._slice00.png\" ... "
               "\"..._slice{value:02d}.png\").", value=depth - 1),
            0, depth,
        )

    encoder_quality = _TEXTURE_QUALITY_TO_ENCODER.get(texture_quality, "best")
    try:
        data.set_images(slices, quality=encoder_quality)
        data.save()
    except Exception as e:
        return tr("Не удалось импортировать срезы текстуры: {error}\n{format_exc}", error=e, format_exc=traceback.format_exc()), 0, depth

    return None, matched, depth
