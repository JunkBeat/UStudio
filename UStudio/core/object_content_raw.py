"""Content raw: export/import of a type's own pixel/audio/video data, including custom resources."""

from core.i18n import tr
import ntpath
import os
import shutil
import tempfile
import traceback
from pathlib import Path
from typing import Optional, Tuple
from UnityPy.environment import simplify_name
from UnityPy.files.BundleFile import BundleFile
from UnityPy.helpers.ResourceReader import get_resource_data
from UnityPy.streams import EndianBinaryReader
from .file_utils import safe_join
from .gc_freeze import collect_everything

from .backup import BackupError, create_backup
from .object_common import _INLINE_CONTENT_FIELD, _STREAM_FIELD_INFO, _register_pending_resource_temp_file, safe_parse_dict, write_error_reason
from .object_export import build_export_stem
from .object_resources import resolve_cab_source


def _self_written_ranges(environment) -> dict:
    """Per-Environment (i.e. per load session), not persisted: {key -> {(offset, size), ...}} of
    byte ranges THIS session's own content-raw imports produced — never the object's original,
    as-shipped range. See can_reclaim's use of this below for why the distinction matters."""
    ranges = getattr(environment, "_content_raw_self_written_ranges", None)
    if ranges is None:
        ranges = {}
        environment._content_raw_self_written_ranges = ranges
    return ranges


def _mark_self_written(environment, key, offset: int, size: int) -> None:
    _self_written_ranges(environment).setdefault(key, set()).add((offset, size))


def _is_self_written(environment, key, offset, size) -> bool:
    return offset is not None and size is not None and (offset, size) in _self_written_ranges(environment).get(key, set())


def _backed_up_paths(environment) -> set:
    paths = getattr(environment, "_content_raw_backed_up_paths", None)
    if paths is None:
        paths = set()
        environment._content_raw_backed_up_paths = paths
    return paths


def _ensure_resource_backup(environment, target_path: str, backup_before_overwrite: bool,
                            backup_keep_latest: Optional[int]) -> Optional[str]:
    """Backs up `target_path` the FIRST time any content-raw import is about to write to it THIS
    session — mirroring "Save Game Files"'s own "snapshot the original right before the first
    overwrite" guarantee, which never otherwise applies to a loose .resource/.resS file (it has no
    objects of its own, so it's never a save "root" — see find_modified_roots()). Returns an error
    string (nothing written) on a genuine backup failure, else None.

    Marks the path as "seen" regardless of backup_before_overwrite's value, so flipping the setting
    ON mid-session after this file was already (unprotected) written to once doesn't try to back up
    already-mutated content and call that "the original" — there is no second chance at a pristine
    copy once the first write already happened."""
    key = os.path.normcase(os.path.abspath(target_path))
    seen = _backed_up_paths(environment)
    if key in seen:
        return None
    seen.add(key)
    if not backup_before_overwrite:
        return None
    try:
        create_backup([Path(target_path)], getattr(environment, "_content_raw_backup_root", None),
                      keep_latest=backup_keep_latest, reason="content_raw")
    except BackupError as e:
        return str(e)
    return None


def set_resource_backup_root(environment, root) -> None:
    """Where THIS session's backups of loose resource files go (None = the standard backup folder). The CLI's
    --backup-dir sets it: without that a resource file's backup landed in the standard folder while the .assets files
    it belongs to were backed up into --backup-dir, so `backup restore --backup-dir` could not find it."""
    environment._content_raw_backup_root = Path(root) if root else None


def resource_files_written(environment) -> list:
    """Loose resource files THIS session's imports already modified on disk. The "original" target mode
    writes a .resource/.resS file at once, not at save time (see _write_original_loose_resource), so an
    import that is abandoned afterwards (the CLI refusing to save because a patch failed) has already
    touched them; this lists them so the caller can say so. Custom (separate) resources are only spooled
    until a save and are not listed."""
    return sorted(getattr(environment, "_content_raw_written_files", None) or ())


def export_object_content_raw(obj, output_dir: Path) -> Tuple[Optional[Path], Optional[str], bool]:
    """Mirrors export_object()'s (out_path, message, skipped) shape. skipped=True
    means there was genuinely nothing to export (neither an external resource nor
    a known inline field for this type) — not an error."""
    type_name = obj.type.name
    field_info = _STREAM_FIELD_INFO.get(type_name)
    if field_info is None:
        return None, tr("Тип \"{type_name}\" не хранит данные во внешнем ресурсе.", type_name=type_name), True

    struct_field, source_key, offset_key, size_key = field_info
    try:
        struct_value = obj.peek_field((struct_field,))
        declared_path = (struct_value or {}).get(source_key) or ""
        stem = build_export_stem(obj)

        if not declared_path:
            inline_field = _INLINE_CONTENT_FIELD.get(type_name)
            if inline_field is None:
                return None, tr("Данные хранятся внутри объекта (не во внешнем ресурсе) — экспорт содержимого недоступен для этого типа."), True
            full, err = safe_parse_dict(obj)
            if full is None:
                return None, tr("Не удалось прочитать данные объекта: {error}", error=err), False
            # inline_field might genuinely not exist in THIS object's own schema
            # (e.g. AudioClip's m_AudioData only exists pre-Unity-5 — see
            # _INLINE_CONTENT_FIELD's own comment) — distinguished from "field
            # exists but is empty" so this never silently claims there's nothing
            # to export when actually the field name just doesn't apply here.
            if inline_field not in full:
                return None, tr("Поле \"{inline_field}\" отсутствует в схеме этого объекта (эта версия формата его не использует).", inline_field=inline_field), True
            raw = full.get(inline_field) or b""
            if not raw:
                return None, tr("Поле с данными пусто — экспортировать нечего."), True
            out_path = safe_join(output_dir, f"{stem}.resdata.bin")
            with open(out_path, "wb") as f:
                f.write(bytes(raw))
            return out_path, None, False

        offset = int(struct_value.get(offset_key, 0) or 0)
        size = int(struct_value.get(size_key, 0) or 0)
        raw = get_resource_data(declared_path, obj.assets_file, offset, size)

        out_path = safe_join(output_dir, f"{stem}.resdata.bin")
        with open(out_path, "wb") as f:
            f.write(raw)
        return out_path, None, False
    except Exception as e:
        return None, tr("Экспорт содержимого не удался: {error}\n{format_exc}", error=e, format_exc=traceback.format_exc()), False


def _import_inline_content(obj, type_name, file_path) -> Optional[str]:
    """Inline-stored data (no external resource): replaces the type's own bytes field."""
    inline_field = _INLINE_CONTENT_FIELD.get(type_name)
    if inline_field is None:
        return (
            tr("Этот объект хранит данные внутри себя, а не во внешнем ресурсе, и для типа \"{type_name}\" нет "
               "поддержки точечной замены этого поля — используйте Raw-экспорт/импорт или отредактируйте Json "
               "дамп вручную.", type_name=type_name)
        )
    full, err = safe_parse_dict(obj)
    if full is None:
        return tr("Не удалось прочитать текущие данные объекта: {error}", error=err)
    # Must actually exist as a key already — see _INLINE_CONTENT_FIELD's own
    # comment for why this isn't guaranteed (AudioClip's m_AudioData only
    # exists pre-Unity-5). Checked BEFORE reading/writing anything so a
    # field that doesn't apply to this object's schema fails loudly instead
    # of silently setting an unused dict key and reporting success — exactly
    # the bug this project's own testing caught for Texture2D's "image
    # data" (space, not "image_data") before this check existed.
    if inline_field not in full:
        return tr("Поле \"{inline_field}\" отсутствует в схеме этого объекта (эта версия формата его не использует) "
           "— точечная замена недоступна.", inline_field=inline_field)
    try:
        with open(file_path, "rb") as f:
            new_bytes = f.read()
    except Exception as e:
        return tr("Не удалось прочитать файл: {error}", error=e)
    full[inline_field] = new_bytes
    try:
        obj.patch(full)
    except Exception as e:
        return tr("Не удалось применить данные: {write_error_reason}\n{format_exc}", write_error_reason=write_error_reason(e), format_exc=traceback.format_exc())
    return None


def _write_custom_loose_resource(environment, custom_name, resolved_source, new_bytes, old_offset, old_size, can_reclaim):
    """Custom (separate) resource, loose-file flavor: content is spooled to a scratch file and only
    written next to the game at save time. Returns (new_offset, None) or (None, error)."""
    # Real reported bug (fixed once already): writing a BRAND NEW
    # custom-resource file to disk the instant an import runs (rather
    # than only once the user actually saves) left a stray,
    # unreferenced file behind whenever the user imported but never
    # went on to save — nothing else in this app touches disk before
    # an explicit Save, and this shouldn't either. The intended
    # on-disk path is remembered in environment._pending_loose_resources
    # for core.save_manager.py's save flows to actually write out at
    # save time — see that module's own _pending_loose_resources()
    # for why (a raw resource file has no OBJECTS of its own, so it
    # never shows up as a table row/modified root the way a
    # .assets/bundle file does — find_modified_roots() alone can't
    # see it).
    #
    # Real reported follow-up concern about the FIRST fix: holding
    # the accumulated content as one plain Python `bytes` object
    # (environment.cabs[custom_name].bytes) grows unbounded with
    # every import made before the next save — exactly the disk
    # bloat this whole feature exists to avoid, just moved into RAM
    # instead (and audio/video content is precisely the case where
    # that matters). Fixed by spooling to a scratch file under the OS
    # temp directory instead — environment._pending_loose_resource_temp_files
    # tracks (custom_name -> temp_path) alongside the existing
    # (custom_name -> intended_destination_path) mapping. The reclaim/
    # append logic below is the exact same "reclaim my own tail"
    # trick the plain "original" branch two paragraphs down already
    # uses against the REAL target file — applied here against the
    # temp file instead, including the same dispose()+gc.collect()
    # dance before reopening it "r+b" on a second-or-later import
    # into the same custom_name (this function's own earlier reload
    # below leaves a live mmap over it, exactly like the "original"
    # branch's own target_path does — see that branch's long comment
    # for why dispose() alone isn't sufficient, confirmed via live
    # testing there and unchanged here).
    # Prefer the destination already recorded on this custom_name's
    # FIRST import this session, rather than re-deriving it from
    # resolved_source — which, on a reimport, has just been
    # overridden above to the temp_path itself (see that comment);
    # os.path.dirname() of it would be the OS temp directory, not
    # the folder this resource is actually meant to live in. Computed
    # BEFORE the temp file below, which needs it to seed from.
    pending = getattr(environment, "_pending_loose_resources", None)
    existing_target = pending.get(custom_name) if pending else None
    if existing_target is not None:
        target_path = existing_target
    else:
        target_path = os.path.join(os.path.dirname(resolved_source), custom_name)

    temp_files = getattr(environment, "_pending_loose_resource_temp_files", None)
    if temp_files is None:
        temp_files = {}
        environment._pending_loose_resource_temp_files = temp_files
    temp_path = temp_files.get(custom_name)
    if temp_path is None:
        fd, temp_path = tempfile.mkstemp(prefix="ustudio_pending_resource_", suffix=".bin")
        os.close(fd)
        # Real, confirmed bug: this temp file used to always start EMPTY,
        # even when `custom_name` is being REUSED after a reload and
        # target_path already holds real content a PRIOR session saved
        # there. Left alone, this session's save-time write
        # (core.save_manager._copy_file, a plain replace) would silently
        # discard every earlier session's data — reproduced end-to-end:
        # session 1 saves 75 bytes to a custom resource, session 2 reloads,
        # imports a DIFFERENT object into the SAME custom name, saves — the
        # file ends up holding only session 2's bytes, session 1's are gone
        # with no error, no warning, and (being a full replace, not an
        # in-place edit) no backup-before-overwrite could have caught it
        # either, since nothing here was ever "overwriting" in the sense
        # that mechanism checks. Seeding the temp file from whatever is
        # already on disk turns this session's save back into the correct
        # old+new picture instead of a lossy new-only one.
        if os.path.isfile(target_path):
            shutil.copyfile(target_path, temp_path)
        temp_files[custom_name] = temp_path
        _register_pending_resource_temp_file(temp_path)

    current_len = os.path.getsize(temp_path) if os.path.isfile(temp_path) else 0

    # Same hardening as _write_original_loose_resource, and for the same
    # reason — now that the temp file can start SEEDED with real, sizeable
    # pre-existing content (not always empty), "old_offset+old_size happens
    # to equal the current length" is just as plausible a coincidence here
    # as it always was for the "original" resource, and reclaiming on it
    # would truncate/overwrite a PRIOR session's real data in place instead
    # of this session's own. Keyed on temp_path (not custom_name) since
    # that's the actual file being written to.
    reclaim_key = os.path.normcase(os.path.abspath(temp_path))
    reclaimed = False
    if (can_reclaim and old_offset + old_size == current_len
            and _is_self_written(environment, reclaim_key, old_offset, old_size)):
        try:
            stale_reader = environment.get_cab(custom_name)
            if stale_reader is not None:
                dispose = getattr(stale_reader, "dispose", None)
                if dispose is not None:
                    dispose()
                    collect_everything()
            with open(temp_path, "r+b") as f:
                f.seek(old_offset)
                f.write(new_bytes)
                f.truncate(old_offset + len(new_bytes))
            new_offset = old_offset
            reclaimed = True
        except OSError:
            pass
    if not reclaimed:
        try:
            with open(temp_path, "ab") as f:
                new_offset = f.tell()
                f.write(new_bytes)
        except Exception as e:
            return None, tr("Не удалось записать данные во временный файл ресурса: {error}", error=e)

    _mark_self_written(environment, reclaim_key, new_offset, len(new_bytes))

    # Reload so in-session preview/re-export reads the just-written
    # bytes correctly — same reload mechanism (and the same reasons
    # for it) as the "original" branch below; temp_path is always the
    # canonical absolute path we created ourselves, so there's no
    # bare-name/registered_name ambiguity to resolve here at all.
    try:
        environment.load_file(temp_path, is_dependency=True, name=custom_name)
    except Exception as e:
        return None, (
            tr("Данные сохранены, но программа не смогла обновить их у себя: {error}. Загрузите файлы заново, "
               "прежде чем снова открывать этот объект.", error=e)
        )

    pending = getattr(environment, "_pending_loose_resources", None)
    if pending is None:
        pending = {}
        environment._pending_loose_resources = pending
    pending[custom_name] = target_path
    return new_offset, None


def _write_original_loose_resource(environment, resolved_source, registered_name, new_bytes, old_offset, old_size, can_reclaim,
                                   backup_before_overwrite: bool = False, backup_keep_latest: Optional[int] = None):
    """The resource file the object already points at, written directly on disk, right now.
    Returns (new_offset, None) or (None, error)."""
    # Written directly on disk, live, right now — same established
    # behavior as before the custom-resource feature existed.
    target_path = resolved_source
    target_load_name = registered_name

    # Real, confirmed gap: this file has no objects of its own, so it's never a
    # save "root" (find_modified_roots()) — "Save Game Files"'s own
    # backup-before-overwrite NEVER covers it, even with the setting on. This is
    # the only point where its pre-edit content could ever be captured, since
    # the write below happens immediately, not at some later "Save" step.
    backup_error = _ensure_resource_backup(environment, target_path, backup_before_overwrite, backup_keep_latest)
    if backup_error:
        return None, tr("Не удалось создать резервную копию ресурса перед записью: {backup_error}", backup_error=backup_error)

    current_len = os.path.getsize(target_path) if os.path.isfile(target_path) else None
    # Reclaim: this object's own previous write is still sitting at
    # the exact tail of the target file (nothing else was appended
    # after it since) — overwrite it in place and truncate to the new
    # size instead of appending, so repeatedly re-importing the SAME
    # object (a normal iterative-testing workflow) doesn't leave every
    # earlier version as permanent dead weight in the file. Never
    # touches bytes before old_offset — every other object's own
    # range is untouched either way.
    #
    # Real, confirmed gap: "this object's own previous write" was never actually
    # checked — only that old_offset+old_size happens to equal the file's current
    # length, which can just as easily be true of the object's ORIGINAL, never-
    # touched data (Unity serializes resource files sequentially, so "this
    # object's data happens to be the last thing in the file" is a common,
    # unremarkable coincidence, not a rare one). Gated below on
    # _is_self_written() — a range only ever enters that set via THIS session's
    # OWN prior _mark_self_written() call, right after a write it made itself —
    # so a true first-ever import into an object can never truncate/overwrite
    # pristine bytes in place, regardless of where they happen to sit.
    reclaim_key = os.path.normcase(os.path.abspath(target_path))
    reclaimed = False
    if (can_reclaim and current_len is not None and old_offset + old_size == current_len
            and _is_self_written(environment, reclaim_key, old_offset, old_size)):
        # Real finding from live testing (not assumed): opening the SAME
        # file "r+b" (needed to seek/overwrite/truncate in place) reliably
        # raised PermissionError on Windows, because this process still
        # had THIS exact resource's own mmap view open from the PRIOR
        # import's reload (every content-raw import ends by calling
        # environment.load_file() to refresh environment.cabs — see the
        # "ab" branch's own long comment below for why that's needed —
        # which is exactly what leaves a live mmap sitting here on the
        # very next call). Releasing that view (same .dispose() mechanism
        # core.save_manager.prepare_overwrite already uses for the
        # identical class of "this process still has it mapped" problem)
        # is necessary but — confirmed by testing, not assumed — NOT
        # sufficient on its own: CPython's memoryview/mmap teardown
        # didn't actually release the OS-level mapping until an explicit
        # gc.collect() ran too (a live repro reliably reproduced "still
        # locked" immediately after dispose() alone, and reliably
        # succeeded once gc.collect() followed it — consistent with a
        # reference cycle somewhere in the view chain that plain
        # refcounting alone doesn't unwind synchronously). Still wrapped
        # in its own try/except and never the only path: reclaim is a
        # pure optimization with no correctness requirement to succeed —
        # falling back to a plain append on ANY remaining failure here is
        # always safe and never worse than this function's pre-reclaim
        # behavior.
        try:
            stale_reader = environment.get_cab(target_load_name) if target_load_name else None
            if stale_reader is not None:
                dispose = getattr(stale_reader, "dispose", None)
                if dispose is not None:
                    dispose()
                    collect_everything()
            with open(target_path, "r+b") as f:
                f.seek(old_offset)
                f.write(new_bytes)
                f.truncate(old_offset + len(new_bytes))
            new_offset = old_offset
            reclaimed = True
        except OSError:
            pass
    if not reclaimed:
        try:
            with open(target_path, "ab") as f:
                new_offset = f.tell()
                f.write(new_bytes)
        except Exception as e:
            return None, tr("Не удалось записать данные в файл ресурса \"{target_path}\": {error}", target_path=target_path, error=e)

    # This write's own range is now fair game for a LATER reimport of this same
    # object to reclaim — see the gate above for why only self-written ranges
    # ever qualify.
    _mark_self_written(environment, reclaim_key, new_offset, len(new_bytes))
    written = getattr(environment, "_content_raw_written_files", None)
    if written is None:
        written = environment._content_raw_written_files = set()
    written.add(os.path.abspath(target_path))

    # Real finding from a live test against the Petscop fixture (not assumed): the
    # append above lands on disk fine (confirmed no mmap-lock conflict, appending
    # past an existing read-only mmap's mapped length is safe on this Windows
    # setup — unlike the documented in-place-overwrite/replace case), but
    # environment.cabs still holds the OLD reader, whose mmap only covers the
    # file's PRE-append length. Left alone, any read at the new offset (an
    # immediate re-preview of this same object, or a second content-raw import
    # against the same resource file) would read out-of-bounds/stale data, not
    # what was just written. Environment.load_file() already has a "this name is
    # already loaded, may have changed on disk" reload path (clears the bundle
    # cache and re-opens+re-mmaps unconditionally).
    #
    # Real bug found and fixed via a live AudioClip round-trip against Petscop
    # (which ships a full BACKUP/ mirror of the whole install, see CLAUDE.md):
    # this used to pass only ntpath.basename(declared_path) — a BARE name, e.g.
    # "sharedassets60.resource" — trusting Environment.load_file()'s own
    # path-guessing fallback (self.path/basename, then find_sensitive_path) to
    # rediscover the SAME physical file resolve_cab_source() already found
    # above. That guess is only a single-level, non-recursive check
    # (find_sensitive_path never walks subdirectories) — it silently returns
    # None whenever the real file lives more than one folder below the
    # environment's root, which is exactly Petscop's own layout
    # (BACKUP/Petscop_Data/... and Petscop_Data/... are both two levels down).
    # load_file() then returns None with NO exception raised — the bare append
    # above still landed correctly on disk, but the reload silently did
    # NOTHING, leaving environment.cabs stuck on the stale pre-append reader.
    #
    # First fix attempt — pass resolved_source (the absolute path) as BOTH
    # the file to open and the name to register under — closed the Petscop
    # case but introduced a DIFFERENT real bug, caught via a live report
    # against a much bigger real fixture (Truck-kun, a 91,618-object,
    # partial/filtered load): a resource that was never part of the initial
    # eager file list — genuinely common, since resource/.resS companion
    # files are only ever registered LAZILY, the first time something reads
    # them (see this function's own docstring on resolve_cab_source, and
    # that function's own two already-documented real bugs) — gets
    # registered under its BARE name the first time (e.g. "resources.
    # resource", via SerializedFile.load_dependencies()'s own bare-name
    # call). Passing the ABSOLUTE path as both file AND name to THIS
    # reload made `register_cab(absolute_path, f)` compute the same shared
    # key but with existing_name ("resources.resource", bare) != name
    # (the absolute path) — Environment.register_cab()'s own
    # cab_collision_policy machinery (correctly designed to keep two
    # GENUINELY different files from clobbering each other, e.g. Petscop's
    # own BACKUP/ duplicates) can't tell "same file, two different name
    # spellings" apart from "two different files, same basename" — under
    # the default "keep_first" policy it silently logged a collision and
    # RETURNED WITHOUT UPDATING environment.cabs[key] at all, leaving the
    # append import "succeed" while the in-memory reader stayed stale
    # forever after. Confirmed via a live repro: the resource file on disk
    # was the exact correct post-append size, but re-reading it through
    # this app reported the OLD, pre-append length — proving the write
    # succeeded and only the in-memory registration was ever wrong.
    #
    # Real fix: resolve_cab_source() now also returns registered_name — the
    # RAW string environment._cab_source_names[key] already holds (bare or
    # absolute, whichever originally won the slot) — passed here as
    # load_file()'s explicit `name=` argument, decoupled from `file` (which
    # stays resolved_source, the guaranteed-correct absolute path to
    # actually reopen). This makes stream_name equal registered_name again,
    # so `stream_name in self.files` is True (this exact name, however it
    # was spelled, was registered at initial load) — taking load_file()'s
    # "already loaded, may have changed on disk" branch — and
    # register_cab(registered_name, f)'s own existing_name check sees
    # registered_name == registered_name, never treating this as a
    # collision, regardless of whether that name happens to be bare or
    # absolute. Verified against BOTH cases end-to-end: Petscop (resource
    # registered via its absolute path at initial folder scan) and a
    # simulated lazy bare-name registration matching Truck-kun's own
    # reported failure — both now correctly reflect the just-appended
    # bytes immediately, with zero cab_collision_policy log noise.
    try:
        environment.load_file(target_path, is_dependency=True, name=target_load_name)
    except Exception as e:
        return None, (
            tr("Данные сохранены, но программа не смогла обновить их у себя: {error}. Загрузите файлы заново, "
               "прежде чем снова открывать этот объект.", error=e)
        )
    return new_offset, None


def _write_bundle_custom_resource(environment, bundle, reader, custom_name, new_bytes, old_offset, old_size, can_reclaim):
    """Custom resource inside the object's own bundle (in memory; persisted by the normal save).
    Returns (new_offset, None) or (None, error)."""
    # get_writeable_cab() is UnityPy's own existing mechanism for
    # exactly this — get-or-create a named, writable entry inside the
    # bundle. Idempotent by name: a SECOND call with the same
    # custom_name (a later import, this session or a future one after
    # reloading) hands back the SAME writer rather than creating a
    # new one, which is what makes "specify the resource name once,
    # every subsequent import accumulates into it" work for free.
    # Raises ValueError if custom_name collides with a real entry
    # that ISN'T a writer (e.g. it happens to match an existing
    # resource/asset name) — surfaced as a clear error rather than
    # letting it propagate as a bare traceback.
    try:
        writer = bundle.get_writeable_cab(custom_name)
    except ValueError as e:
        return None, tr("Не удалось использовать «{custom_name}» как отдельный ресурс: {error}", custom_name=custom_name, error=e)

    current_len = writer.Length
    if can_reclaim and old_offset + old_size == current_len:
        writer.Position = old_offset
        writer.write(new_bytes)
        # EndianBinaryWriter has no public truncate of its own — its
        # backing stream (a BytesIO for the in-memory case
        # get_writeable_cab() always constructs) does. Only needed
        # when new_bytes is SHORTER than the reclaimed range; a
        # same-or-larger write already extends the stream on its own.
        writer.stream.truncate(old_offset + len(new_bytes))
        new_offset = old_offset
    else:
        writer.Position = writer.Length
        new_offset = writer.Position
        writer.write(new_bytes)
    # register_cab(), not a direct environment.cabs[...] assignment —
    # real bug caught by testing: the ORIGINAL-resource branch below
    # can get away with touching environment.cabs directly because
    # environment._cab_source_names[key] was already populated for
    # that name by the initial full load; a brand-new custom_name has
    # no such prior registration, so skipping register_cab() left
    # _cab_source_names without an entry for it at all — the very
    # next resolve_cab_source() call for this SAME object (a second
    # import into it) then failed with "resource not found" even
    # though the reader itself was reachable via a direct cabs
    # lookup. register_cab() is also correctly idempotent for the
    # repeat-registration case (same name, same writer, every call
    # after the first): its own collision check only fires when the
    # NAME differs from what's already registered under that key.
    #
    # A READER snapshot of the writer's current bytes is registered
    # here, NOT the writer itself — real reported bug, the same
    # class already fixed once for the loose-file custom-resource
    # case (see that branch's own comment on why a Writer can't
    # stand in for a Reader) but missed here: get_resource_data()
    # (used by BOTH re-preview and export, for AudioClip/VideoClip)
    # does `reader.Position = offset; reader.read_bytes(size)` —
    # EndianBinaryWriter has neither, so the very first re-preview
    # of an object just imported into a bundle-internal custom
    # resource crashed with AttributeError. This went uncaught by
    # this feature's own earlier verification because that test used
    # a Texture2D fixture, which never reads via get_resource_data()
    # at all (it decodes through .image/m_StreamData instead) — only
    # AudioClip/VideoClip do, so the gap was invisible until a real
    # VideoClip exercised it. The WRITER itself stays exactly what
    # bundle.files[custom_name] holds (via get_writeable_cab(),
    # untouched) and what a LATER re-import's own can_reclaim/
    # writer.Length checks read from — only the environment.cabs
    # entry used for READS changes; save_fs()'s own serialization
    # path never goes through environment.cabs at all, so this
    # doesn't affect what actually gets persisted.
    environment.register_cab(custom_name, EndianBinaryReader(writer.bytes, endian=getattr(reader, "endian", ">")))
    bundle.mark_changed()
    return new_offset, None


def _write_bundle_original_resource(environment, bundle, resolved_source, new_bytes, old_offset, old_size, can_reclaim):
    """The bundle-internal resource the object already points at (in memory).
    Returns (new_offset, None) or (None, error)."""
    if resolved_source not in bundle.files:
        return None, (
            tr("Не удалось найти ресурс \"{resolved_source}\" в бандле, содержащем этот объект — точечный импорт "
               "содержимого невозможен.", resolved_source=resolved_source)
        )
    old_entry = bundle.files[resolved_source]
    try:
        old_bytes = old_entry.bytes
    except Exception as e:
        return None, tr("Не удалось прочитать текущее содержимое ресурса: {error}", error=e)

    # Reclaim: same idea as the loose-file branch above, including the same
    # hardening against reclaiming pristine (never-self-written) data — see
    # _write_original_loose_resource's own comment on why _is_self_written()
    # matters here. This one is lower-stakes (nothing is written to DISK until
    # the normal Save flow rebuilds the bundle, and that flow already backs up
    # the still-untouched original bundle file before overwriting it), but the
    # same hardening costs nothing extra to apply for consistency.
    reclaim_key = (id(bundle), resolved_source)
    if (can_reclaim and old_offset + old_size == len(old_bytes)
            and _is_self_written(environment, reclaim_key, old_offset, old_size)):
        combined = old_bytes[:old_offset] + new_bytes
        new_offset = old_offset
    else:
        combined = old_bytes + new_bytes
        new_offset = len(old_bytes)
    _mark_self_written(environment, reclaim_key, new_offset, len(new_bytes))

    new_reader = EndianBinaryReader(combined, endian=getattr(old_entry, "endian", ">"))
    new_reader.flags = getattr(old_entry, "flags", 0)
    bundle.files[resolved_source] = new_reader
    environment.cabs[simplify_name(resolved_source)] = new_reader
    bundle.mark_changed()
    return new_offset, None


def import_object_content_raw(
    obj, file_path: Path, *,
    resource_target_mode: str = "original",
    resource_name: Optional[str] = None,
    backup_before_overwrite: bool = False,
    backup_keep_latest: Optional[int] = None,
) -> Optional[str]:
    """Writes the file's bytes into the resolved resource and repoints this
    object's own source/offset/size fields at the new range. Three storage
    shapes:
      - loose external file: written directly on disk, live, right now.
      - bundle-internal resource (compressed block, not a real file on disk):
        written IN MEMORY only, via a writable bundle.files[] entry — see
        the branch below for why persisting this to disk is deliberately left
        to the existing "Save game files" flow rather than triggered here.
      - inline-stored data (declared_path empty): patches the type's own inline
        field directly instead (_INLINE_CONTENT_FIELD) — there's no separate
        resource to write to at all, but the bytes are still a plain typetree
        field, replaceable the same way import_object_converted() already does
        for Font/TextAsset.

    resource_target_mode ("original", default, or "custom_resource") and
    resource_name control WHERE the bytes for the first
    two shapes land — see CONFIG.resource_target_mode's own comment for
    the real request this answers (the original resource can be huge; a
    separate, named resource keeps patches self-contained and shareable).
    "custom_resource" with no name configured is an error, not a silent
    fallback to "original" — that fallback would silently defeat the whole
    point the one time it would matter (the user explicitly turned this on).

    Within whichever resource ends up as the target, a re-import always
    tries to RECLAIM this exact object's own immediately-preceding write
    first (overwrite it in place, truncate to the new size) before falling
    back to appending — see the reclaim-vs-append comment below for why this
    is safe (never touches or moves any OTHER object's bytes) and what it
    doesn't attempt (no general "shift everyone after this point" repack).

    backup_before_overwrite/backup_keep_latest (mirroring CONFIG's own fields
    of the same name) only affect the loose "original" resource shape — the
    one write in this whole function that happens directly to disk, live,
    with no later "Save" step to fall back on if it turns out wrong. When
    True, that resource file is backed up (core.backup.create_backup) the
    FIRST time this session touches it, before the write — see
    _ensure_resource_backup()'s own docstring. The other two shapes need no
    such call: bundle-internal writes stay in memory until the normal Save
    flow rebuilds the archive, which already backs up the still-untouched
    original bundle first; a fresh custom resource has no prior content to
    protect in the first place."""
    type_name = obj.type.name
    field_info = _STREAM_FIELD_INFO.get(type_name)
    if field_info is None:
        return tr("Тип \"{type_name}\" не хранит данные во внешнем ресурсе — используйте Raw-импорт.", type_name=type_name)

    struct_field, source_key, offset_key, size_key = field_info
    try:
        struct_value = obj.peek_field((struct_field,))
    except Exception as e:
        return tr("Не удалось прочитать ссылку на ресурс: {error}", error=e)

    struct_value = struct_value or {}
    declared_path = struct_value.get(source_key) or ""
    old_offset = struct_value.get(offset_key)
    old_size = struct_value.get(size_key)
    if not declared_path:
        return _import_inline_content(obj, type_name, file_path)

    environment = obj.assets_file.environment
    reader, resolved_source, registered_name = resolve_cab_source(environment, declared_path, obj.assets_file)
    if reader is None or resolved_source is None:
        return tr("Не удалось найти файл ресурса \"{declared_path}\" среди загруженных файлов.", declared_path=declared_path)

    try:
        file_path = Path(file_path)
        with open(file_path, "rb") as f:
            new_bytes = f.read()
    except Exception as e:
        return tr("Не удалось прочитать файл: {error}", error=e)

    use_custom = resource_target_mode == "custom_resource"
    custom_name = (resource_name or "").strip()
    if use_custom and not custom_name:
        return (
            tr("Выбран режим «отдельный ресурс», но имя ресурса не задано. Укажите имя в настройках или "
               "вернитесь к «исходному ресурсу».")
        )
    # Reclaim-vs-append: only meaningful when this object's PREVIOUS write (if
    # any) landed in the exact same resource we're about to write into now. In
    # "original" mode that's always true by construction — declared_path IS
    # resolved_source, there's nothing else it could be. In "custom_resource"
    # mode it's only true if a PRIOR import already redirected this object into
    # this exact custom name (comparing basenames, case-insensitively, via the
    # same simplify_name() the cab registry itself uses) — the very first
    # import into a fresh custom resource, or one done under a since-changed
    # name, correctly falls through to a plain append instead.
    if use_custom:
        target_is_same_as_before = bool(declared_path) and simplify_name(ntpath.basename(declared_path)) == simplify_name(custom_name)
    else:
        target_is_same_as_before = True
    can_reclaim = target_is_same_as_before and old_offset is not None and old_size is not None

    # Real bug found via testing, not assumed (never previously exercised: a
    # REIMPORT into a custom resource already active this session): once a
    # loose custom resource is registered via environment.load_file(temp_path,
    # ..., name=custom_name) below, resolve_cab_source() on a LATER call
    # correctly finds the registered cab but reports resolved_source as that
    # same BARE custom_name, not the real absolute temp_path — register_cab()/
    # load_file() preserve whichever spelling first won the name slot, and a
    # bare override name is exactly what this reload always passes. Left
    # alone, the isabs() check just below would then misclassify a reimport
    # as "not a loose file" and route it into the bundle-internal branch
    # instead — silently creating an unrelated bundle-internal entry under
    # the same name rather than reclaiming/appending the real temp file, and
    # never reaching disk via save_manager._pending_loose_resources() at all.
    # Overriding resolved_source here — to the real, always-absolute
    # temp_path already tracked in environment._pending_loose_resource_temp_files
    # — routes it correctly; the branch below itself avoids re-deriving
    # target_path's directory from it for the same reason (see its own
    # comment).
    if use_custom:
        _existing_temp_files = getattr(environment, "_pending_loose_resource_temp_files", None)
        if _existing_temp_files and custom_name in _existing_temp_files:
            resolved_source = _existing_temp_files[custom_name]

    if isinstance(resolved_source, str) and os.path.isabs(resolved_source):
        # Loose external file.
        if use_custom:
            new_offset, error = _write_custom_loose_resource(
                environment, custom_name, resolved_source, new_bytes, old_offset, old_size, can_reclaim)
        else:
            new_offset, error = _write_original_loose_resource(
                environment, resolved_source, registered_name, new_bytes, old_offset, old_size, can_reclaim,
                backup_before_overwrite=backup_before_overwrite, backup_keep_latest=backup_keep_latest)
    else:
        # Bundle-internal resource (lives inside a compressed block, not a loose
        # file on disk) — append IN MEMORY instead, by replacing the bundle's own
        # files[] entry with a fresh EndianBinaryReader holding old+new bytes.
        # Deliberately a READER, not an EndianBinaryWriter: the replaced entry
        # must stay usable for READS too (a re-preview of this exact object, or
        # export_object_content_raw() on it, both go through
        # get_resource_data()/_get_resource_data(), which does
        # `reader.Position = offset; reader.read_bytes(size)` — an
        # EndianBinaryWriter has neither, and would raise AttributeError the
        # moment either was attempted; EndianBinaryReader_Memoryview supports
        # both `.bytes` (for save_fs()'s own write path) and `.Position`/
        # `.read_bytes()` in one object). Materializes the WHOLE resource once
        # (old bytes + new bytes) rather than streaming the append — an accepted
        # cost for this lightweight per-object path (mirrors the loose-file
        # branch above, which doesn't stream either); a resource file itself is
        # normally far smaller than the whole bundle, so this is nowhere near the
        # full-archive-rebuild cost class CLAUDE.md documents elsewhere.
        #
        # Nothing is written to the actual bundle file on disk here: marking the
        # bundle changed (mark_changed(), plus obj.patch() below marking this
        # object's own SerializedFile changed too) is exactly what
        # core/save_manager.py's find_modified_roots() already keys off of for
        # the File menu's existing "Save game files"/"Save game files as..."
        # actions — those already do a full BundleFile.save() rebuild for any
        # root with a pending edit, so persisting this is just the normal save
        # step, not something this function needs to trigger itself. Deliberately
        # NOT auto-rebuilding-and-writing the whole archive here: that would turn
        # every single small content-raw edit into an implicit multi-minute (or,
        # on the largest fixtures, multi-GB-of-RAM) full-archive rebuild the user
        # never asked for at that moment.
        bundle = obj.assets_file.parent
        if not isinstance(bundle, BundleFile):
            return (
                tr("Не удалось найти ресурс \"{resolved_source}\" рядом с этим объектом — импорт содержимого "
                   "невозможен.", resolved_source=resolved_source)
            )

        if use_custom:
            new_offset, error = _write_bundle_custom_resource(
                environment, bundle, reader, custom_name, new_bytes, old_offset, old_size, can_reclaim)
        else:
            new_offset, error = _write_bundle_original_resource(
                environment, bundle, resolved_source, new_bytes, old_offset, old_size, can_reclaim)

    if error:
        return error

    full, err = safe_parse_dict(obj)
    if full is None:
        return tr("Данные добавлены, но не удалось прочитать текущие данные объекта: {error}", error=err)
    # "original" mode never redirects — writing declared_path back is a no-op
    # (same value the field already held). "custom_resource" mode repoints the
    # object at whichever resource it actually ended up in (custom_name for
    # both storage shapes — loose and bundle-internal alike).
    full[struct_field][source_key] = custom_name if use_custom else declared_path
    full[struct_field][offset_key] = new_offset
    full[struct_field][size_key] = len(new_bytes)
    try:
        obj.patch(full)
    except Exception as e:
        return (
            tr("Данные добавлены, но не удалось обновить ссылку на них в объекте: {error}\n{format_exc}", error=e, format_exc=traceback.format_exc())
        )
    return None
