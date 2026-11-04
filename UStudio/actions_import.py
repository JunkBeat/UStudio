"""Imports of ObjectActionsController: one file into one object, Texture2DArray slices, files into a selection,
folder (mass) imports with the match list, and the sdf_map.txt-driven SDF generation from a folder.

Kept out of object_actions.py as a mixin (ObjectActionsController inherits it). Behaviour is unchanged; this is a
mechanical move (every method body is byte-identical to its old place in object_actions.py)."""

from core.i18n import tr, trn
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import QDialog, QFileDialog, QMessageBox

from config import CONFIG, LogLevel, save_persisted_config
from dialogs import ConvertedImportSettingsDialog, ImportMatchDialog, SDFMapImportSettingsDialog
from core.loader import collect_serialized_files
from core.progress import OperationCancelled, ProgressThrottle
from core.object_preview import (
    MatchedPatch, CONVERTED_IMPORT_SUPPORTED_TYPES, IMPORT_WARNING_PREFIX, ROW_FIELD_UNRESOLVED,
    apply_matched_patch, classify_import_mode, get_row_name, import_texture_array_slices, match_patch_files,
)
from core.sdf_generator import SDFGenerationError, add_characters_to_font_asset
from task_queue import TaskKind
from gui_common import exec_and_dispose


class ImportActionsMixin:
    # --- Sprite mesh -> rectangle («Сделать сетку прямоугольной») ---

    def make_sprite_meshes_rectangular(self, items: list):
        """For sprites whose texture was edited directly: a «Tight» mesh follows the old picture's outline and
        hides new pixels outside it in game. Quick (one typetree read/write per sprite), so not queued."""
        from core.sprite_mesh import ALREADY_FULL_RECT, make_sprite_full_rect
        win = self.main_window
        changed = 0
        for item in items:
            obj = item.get("obj_ref")
            if obj is None or item.get("type") != "Sprite":
                continue
            done, message = make_sprite_full_rect(obj)
            name = get_row_name(item)
            if done:
                changed += 1
                self._refresh_row_after_patch(item, obj)
                if len(items) == 1:
                    win.log(f"{name}: {message}.")
            else:
                win.log(f"{name}: {message}.", LogLevel.INFO if message == tr(ALREADY_FULL_RECT) else LogLevel.WARNING)
        if len(items) > 1:
            win.log(tr("Сетка заменена прямоугольником у спрайтов: {count} из {total}.", count=changed, total=len(items)))

    # --- Import / export a single object (queued) ---

    def import_from_file(self, item_data: dict):
        """File-based counterpart to open_json_editor_dialog's inline text edit —
        always silent, uses whatever's saved in CONFIG. See
        import_from_file_with_settings() for the deliberate, dialog-opening
        counterpart (only offered in the menu for types that actually have
        settings worth showing)."""
        self._import_from_file_impl(item_data, with_settings=False)

    def import_from_file_with_settings(self, item_data: dict):
        """Same as import_from_file(), but always opens
        ConvertedImportSettingsDialog first — this is the ONLY way that dialog
        is reached; there's no "ask before every import" toggle anymore (see
        config.py's own comment on texture_import_format_mode for why). Only
        ever wired into the menu when item_data's type is in
        CONVERTED_IMPORT_SUPPORTED_TYPES, so this never needs to handle "the
        dialog has nothing relevant to show" itself."""
        self._import_from_file_impl(item_data, with_settings=True)

    def _import_from_file_impl(self, item_data: dict, with_settings: bool):
        """Import mode is decided purely by the chosen file's extension
        (classify_import_mode) — no filename/PathID validation at all, unlike the
        folder-based mass-import paths below: this is already an explicit,
        deliberate action against one already-selected object, so there's no
        ambiguity to confirm."""
        win = self.main_window
        obj = item_data.get("obj_ref")

        file_path, _ = QFileDialog.getOpenFileName(
            win, tr("Выберите файл для импорта"), "",
            tr("Файлы патчей ({patterns})", patterns="*.json *.txt *.bin *.png *.wav *.mp4 *.webm *.mkv *.avi *.mov *.m4v "
               "*.ogv *.ttf *.otf") + ";;" + tr("Все файлы (*)"),
        )
        if not file_path:
            return

        mode = classify_import_mode(file_path)
        if mode is None:
            win.log(tr("Нераспознанное расширение файла: {path}", path=file_path), LogLevel.WARNING)
            return

        texture_kwargs = {}
        type_name = item_data.get("type")
        if mode == "converted" and type_name in CONVERTED_IMPORT_SUPPORTED_TYPES:
            if with_settings:
                texture_kwargs = self._show_converted_import_settings_dialog(
                    type_name, getattr(obj, "platform", None), getattr(obj, "version", None),
                    source_file_path=file_path, obj=obj,
                )
                if texture_kwargs is None:
                    return  # dialog cancelled
            else:
                texture_kwargs = {
                    "texture_quality": CONFIG.texture_import_quality,
                    "texture_mipmaps": CONFIG.texture_import_mipmaps,
                    "texture_format_mode": CONFIG.texture_import_format_mode,
                    "texture_manual_format": CONFIG.texture_import_manual_format,
                    "audio_quality": CONFIG.audio_import_quality,
                }

        # Applies whenever mode == "content_raw" directly, or "converted" for a
        # type (AudioClip/VideoClip) that delegates its actual storage to
        # import_object_content_raw() internally — always read straight from
        # CONFIG, no per-import dialog: this is a session-wide "where do edits
        # land" choice, not a per-file tunable like texture quality/format.
        content_raw_kwargs = {
            "resource_target_mode": CONFIG.resource_target_mode,
            "resource_name": CONFIG.resource_name,
            "backup_before_overwrite": CONFIG.backup_before_overwrite,
            "backup_keep_latest": CONFIG.backup_keep_latest,
        }

        def fn(report_progress, should_cancel):
            patch = MatchedPatch(
                obj=obj, file_path=Path(file_path), mode=mode, display_name=get_row_name(item_data),
                **texture_kwargs, **content_raw_kwargs,
            )
            error = apply_matched_patch(patch, report_progress=report_progress, should_cancel=should_cancel)
            if error and not error.startswith(IMPORT_WARNING_PREFIX):
                raise RuntimeError(error)
            suffix = f" ({error[len(IMPORT_WARNING_PREFIX):]})" if error else ""
            return tr("Импортировано ({mode}): {name}", mode=mode, name=get_row_name(item_data)) + suffix

        # Real reported request: a transcoding video's task-queue row looked
        # identical to any other (fast) import — "Импорт" (the task KIND,
        # shared with every import and correct here, since transcoding is
        # still one step within an import) gave no hint that THIS particular
        # one involves a real, potentially slow encode. Folding it into the
        # TITLE instead of trying to change the row's kind label keeps the
        # shared task_queue_dialog.py code untouched (it's generic across
        # every task kind, not just this one) while still surfacing the
        # distinction where it's actually visible — the row's own text.
        title = get_row_name(item_data)
        if texture_kwargs.get("video_transcode"):
            title = tr("{title} (транскодирование)", title=title)
        task_id = win.task_queue_manager.enqueue(TaskKind.IMPORT, title, fn)
        self._task_followups[task_id] = {
            "title": title,
            "on_success": lambda: self._refresh_row_after_patch(item_data, obj),
        }

    def import_texture_array_slices_from_folder(self, item_data: dict):
        """Folder-based counterpart to import_from_file() for Texture2DArray —
        always silent, uses CONFIG's saved defaults. See
        import_texture_array_slices_from_folder_with_settings() for the
        dialog-opening counterpart."""
        self._import_texture_array_slices_impl(item_data, with_settings=False)

    def import_texture_array_slices_from_folder_with_settings(self, item_data: dict):
        """Same as import_texture_array_slices_from_folder(), but always opens
        ConvertedImportSettingsDialog first (quality/mipmaps only — format is
        always match-original for a Texture2DArray, see
        core.object_preview.import_texture_array_slices's own docstring)."""
        self._import_texture_array_slices_impl(item_data, with_settings=True)

    def _import_texture_array_slices_impl(self, item_data: dict, with_settings: bool):
        win = self.main_window
        obj = item_data.get("obj_ref")

        dir_path = QFileDialog.getExistingDirectory(win, tr("Выберите папку со срезами текстуры"))
        if not dir_path:
            return

        if with_settings:
            texture_kwargs = self._show_converted_import_settings_dialog(
                "Texture2DArray", getattr(obj, "platform", None)
            )
            if texture_kwargs is None:
                return  # dialog cancelled
        else:
            texture_kwargs = {
                "texture_quality": CONFIG.texture_import_quality,
                "texture_mipmaps": CONFIG.texture_import_mipmaps,
            }
        # texture_format_mode/texture_manual_format are irrelevant here (see
        # import_texture_array_slices's docstring — always match-original),
        # and audio_quality never applies to a texture — dropped rather than
        # passed through, since that function's signature doesn't accept any
        # of these.
        texture_kwargs.pop("texture_format_mode", None)
        texture_kwargs.pop("texture_manual_format", None)
        texture_kwargs.pop("audio_quality", None)

        def fn(report_progress, should_cancel):
            error, matched, depth = import_texture_array_slices(obj, Path(dir_path), **texture_kwargs)
            if error:
                raise RuntimeError(error)
            kept = depth - matched
            return tr("Импортировано срезов: {count} из {total} (без изменений: {kept}) — {name}",
                      count=matched, total=depth, kept=kept, name=get_row_name(item_data))

        title = get_row_name(item_data)
        task_id = win.task_queue_manager.enqueue(TaskKind.IMPORT, title, fn)
        self._task_followups[task_id] = {
            "title": title,
            "on_success": lambda: self._refresh_row_after_patch(item_data, obj),
        }

    # --- Folder-based mass import (scoped to a selection, or unscoped across the
    # whole Environment) — see core.object_preview.match_patch_files/MatchedPatch
    # for the filename-matching mechanism this is built on. ---

    def _gather_all_env_candidates(self):
        """Every ObjectReader currently parsed anywhere in the Environment — not
        just table rows (win.raw_data_list only ever holds RICH_PREVIEW_TYPES
        rows) — via core.loader.collect_serialized_files(), which already walks
        bundle-internal files too, "deliberately NOT limited to env.objects/the
        table's own contents" per its own docstring. Does NOT reach objects a
        load-time type filter kept out of memory entirely (a large load with
        "load all assets" off — EnvironmentLoader._derived_type_filter) — those genuinely don't exist as
        ObjectReaders anywhere, not just hidden from the table (confirmed in
        SerializedFile.__init__: a filtered-out object's reader is discarded
        during parsing, never added to self.objects)."""
        win = self.main_window
        if win.env is None:
            return []
        candidates = []
        for sf in collect_serialized_files(win.env):
            source = getattr(sf, "name", "") or ""
            for obj in sf.objects.values():
                candidates.append((obj.path_id, source, obj))
        return candidates

    # --- On-the-fly SDF generation via a dropped sdf_map.txt (+ sibling
    # chars.txt) — see _import_patches_from_folder's own docstring for how
    # this fits alongside (not instead of) the dump/PNG patch matching
    # above, and why it's gated to the whole-environment-scoped entry point
    # only. Real design point confirmed with the user: unlike "Импортировать
    # из папки...", which imports into a SELECTED set of objects, a mapping
    # file's own targets can name ANY object in the game — applying that
    # broader scope through a SELECTION-scoped entry point risks silently
    # reaching objects the user never selected, which is exactly the
    # "affects unselected objects" risk they flagged directly. ---

    @staticmethod
    def _sdf_map_candidates_to_rows(candidates) -> list:
        """Lightweight RowItem-shaped adapter for
        core.sdf_map.resolve_font_map(), which only ever reads
        source/path_id/obj_ref plus name/script_name via
        get_row_name()/get_row_script_name() (which lazily resolve+memoize
        from obj_ref on demand, given ROW_FIELD_UNRESOLVED — see
        core/object_preview.py). Built directly from a (path_id, source,
        obj_ref) triple instead of routing through core.loader.build_row_item(),
        which additionally computes size/container EAGERLY for every single
        candidate — a real, avoidable cost at _gather_all_env_candidates()'s
        own unscoped, whole-Environment scale, for fields resolve_font_map()
        never reads at all."""
        return [
            {
                "path_id": path_id, "source": source, "obj_ref": obj_ref,
                "name": ROW_FIELD_UNRESOLVED, "script_name": ROW_FIELD_UNRESOLVED,
            }
            for path_id, source, obj_ref in candidates
        ]

    def import_patches_from_selection(self, items: list):
        def candidates_fn():
            return [(item["path_id"], item["source"], item["obj_ref"]) for item in items]
        texture_kwargs = self._resolve_bulk_texture_settings(items, with_settings=False)
        self._import_patches_from_folder(candidates_fn, **texture_kwargs)

    def import_patches_from_selection_with_settings(self, items: list):
        """Same as import_patches_from_selection(), but opens
        ConvertedImportSettingsDialog once up front — only ever wired into the
        bulk-selection menu when at least one selected item's type is in
        CONVERTED_IMPORT_SUPPORTED_TYPES (see _show_bulk_context_menu), so
        there's always something real for it to configure."""
        def candidates_fn():
            return [(item["path_id"], item["source"], item["obj_ref"]) for item in items]
        texture_kwargs = self._resolve_bulk_texture_settings(items, with_settings=True)
        if texture_kwargs is None:
            return  # dialog cancelled
        self._import_patches_from_folder(candidates_fn, **texture_kwargs)

    def import_file_into_selection(self, items: list):
        """One file written into EVERY selected object (for example one PNG into all selected
        textures). Only converted formats (image, audio, video, font, text) are accepted: a
        .dump.json / .dump.bin / .resdata.bin holds the complete data of one particular object, so
        writing it into several would overwrite them all with the same content and corrupt them.
        Objects the file does not fit by type are left out and counted; the rest run as one queued
        import task, exactly like a folder import."""
        import dataclasses
        from core.patch_matching import types_for_converted_suffix
        win = self.main_window
        file_path, _ = QFileDialog.getOpenFileName(
            win, tr("Выберите патч-файл для массового применения"), "",
            tr("Изображения, звук, видео, шрифты, текст ({patterns})", patterns="*.png *.wav *.mp4 *.webm *.mkv *.avi "
               "*.mov *.m4v *.ogv *.ttf *.otf *.txt") + ";;" + tr("Все файлы (*)"),
        )
        if not file_path:
            return
        mode = classify_import_mode(file_path)
        if mode in ("json_dump", "raw", "content_raw"):
            QMessageBox.warning(
                win, tr("Импорт файла"),
                tr("Этот патч-файл вероятно не подходит для массовой записи в объекты и может испортить файлы игры."
                   "\n\nДля массовой записи подходят изображения, звук, видео, шрифты и текст."))
            return
        if mode is None:
            win.log(tr("Нераспознанное расширение файла: {path}", path=file_path), LogLevel.WARNING)
            return
        fits = types_for_converted_suffix(file_path)
        eligible = [i for i in items if fits is None or i.get("type") in fits]
        skipped = len(items) - len(eligible)
        if not eligible:
            QMessageBox.information(win, tr("Импорт файла"),
                                    tr("Файл такого формата не подходит ни к одному из выбранных объектов."))
            return
        text = trn(len(eligible), "Файл «{name}» будет записан в {n} объект.", "Файл «{name}» будет записан в {n} объекта.",
                   "Файл «{name}» будет записан в {n} объектов.", name=Path(file_path).name)
        if skipped:
            text += "\n" + tr("Пропущено {count} (неподходящий тип объекта).", count=skipped)
        text += "\n\n" + tr("Продолжить?")
        if QMessageBox.question(win, tr("Импорт файла"), text) != QMessageBox.StandardButton.Yes:
            return
        settings = self._resolve_bulk_texture_settings(eligible, with_settings=False) or {}
        allowed = {f.name for f in dataclasses.fields(MatchedPatch)}
        extra = {k: v for k, v in settings.items() if k in allowed}
        matches = [
            MatchedPatch(obj=item["obj_ref"], file_path=Path(file_path), mode="converted",
                         display_name=get_row_name(item), path_id=item.get("path_id", 0),
                         source=item.get("source", ""), **extra)
            for item in eligible
        ]
        self._start_folder_patch_import(str(Path(file_path).parent), matches)

    def _resolve_bulk_texture_settings(self, items: list, with_settings: bool) -> Optional[dict]:
        """Resolves the texture_* kwargs match_patch_files() needs for a batch
        import — either straight from CONFIG (with_settings=False, or no
        eligible item in the selection at all), or via one
        ConvertedImportSettingsDialog shown up front (there's no per-object
        dialog opportunity in a batch run, same reasoning as the folder-import
        path's own existing comment). Returns None only when the user
        cancelled a shown dialog — callers should abort the whole import in
        that case, same as a cancelled file/folder picker."""
        kwargs = {
            "texture_quality": CONFIG.texture_import_quality,
            "texture_mipmaps": CONFIG.texture_import_mipmaps,
            "texture_format_mode": CONFIG.texture_import_format_mode,
            "texture_manual_format": CONFIG.texture_import_manual_format,
            "audio_quality": CONFIG.audio_import_quality,
            # Always read straight from CONFIG, regardless of with_settings —
            # see _import_from_file_impl's own comment: this is a session-wide
            # setting, ConvertedImportSettingsDialog has no section for it.
            "resource_target_mode": CONFIG.resource_target_mode,
            "resource_name": CONFIG.resource_name,
            "backup_before_overwrite": CONFIG.backup_before_overwrite,
            "backup_keep_latest": CONFIG.backup_keep_latest,
        }
        if not with_settings:
            return kwargs
        eligible_items = [item for item in items if item.get("type") in CONVERTED_IMPORT_SUPPORTED_TYPES]
        if not eligible_items:
            return kwargs
        # _show_bulk_context_menu only ever offers "...с настройками" for a
        # selection that's already a single, homogeneous type, so every
        # eligible item here is guaranteed to share the same type — no need
        # to reconcile multiple types into one dialog.
        type_name = eligible_items[0]["type"]
        platform = getattr(eligible_items[0].get("obj_ref"), "platform", None)
        version = getattr(eligible_items[0].get("obj_ref"), "version", None)
        dialog_kwargs = self._show_converted_import_settings_dialog(type_name, platform, version)
        if dialog_kwargs is None:
            return None  # dialog cancelled
        dialog_kwargs["resource_target_mode"] = CONFIG.resource_target_mode
        dialog_kwargs["resource_name"] = CONFIG.resource_name
        dialog_kwargs["backup_before_overwrite"] = CONFIG.backup_before_overwrite
        dialog_kwargs["backup_keep_latest"] = CONFIG.backup_keep_latest
        # video_transcode_output_path (when present) is a single path the
        # dialog suggested with no real object/file in scope (this is a
        # batch, not one file) — meaningless here and NOT one of
        # match_patch_files()'s own params. Dropped rather than forwarded:
        # match_patch_files() already derives a correct per-object output
        # path next to each matched VideoClip's own patch file (see its own
        # docstring) whenever video_transcode is truthy, so nothing is lost.
        dialog_kwargs.pop("video_transcode_output_path", None)
        return dialog_kwargs

    def _show_converted_import_settings_dialog(self, type_name: str, platform, version=None,
                                                 source_file_path=None, obj=None) -> Optional[dict]:
        """Shows ConvertedImportSettingsDialog seeded from CONFIG, applies and
        persists the result to CONFIG on OK, and returns the resolved
        texture_*/audio_quality kwargs for apply_matched_patch()/
        match_patch_files(). None means the user cancelled — shared by the
        single-file and bulk-selection "...с настройками" entry points so the
        apply/persist logic can't drift between the two. `version` (the
        object's own UnityVersion, when known) drives BC7 version gating —
        see ConvertedImportSettingsDialog's own comment. `source_file_path`
        (the file already chosen via the Open dialog, when known) only
        affects the VideoClip section's suggested output filename. `obj`
        (the object BEING imported into, when known and singular — omitted
        for a bulk selection with no one object to derive this from) is used
        only to pre-select the transcode format below.

        video_transcode_target/video_transcode_quality DO persist to CONFIG
        like every other axis here (a real reported request: the dialog
        used to always reset to "h264"/70, which read as a bug the moment a
        user picked "vp8" for one import and the NEXT one silently used
        "h264" again without them re-selecting it). video_transcode itself
        (the checkbox) and video_transcode_output_path deliberately do NOT —
        there's no CONFIG.video_transcode default at all (see config.py):
        transcoding must always be a deliberate, explicitly re-checked
        choice, never something that could silently turn itself back on;
        and a remembered OUTPUT PATH would either collide across different
        objects or silently overwrite a previous import's own result.

        Real, direct follow-up request on top of the above: once
        video_transcode_target started persisting, it persisted too
        bluntly — always the LAST format picked, even when the object
        actually being imported into already declares a different one
        (visibly shown right there in the Preview tab's format label). This
        used to be handled by silently overriding the remembered CONFIG
        value with whatever target matched the object's own current
        container — replaced (per direct feedback that an auto-changing
        default was confusing) by "Same as original", an explicit, always-
        first, rememberable dropdown choice in the dialog itself
        (converted_import_settings_dialog.py) that resolves to the matching
        target at accept() time — `obj` is passed straight through to the
        dialog so it can do that resolution (and, if the object's own
        container isn't one of the two real targets at all, ask once via
        its own accept() override whether to fall back to one). CONFIG still
        remembers whichever literal choice was made (get_values()'s own
        "video_transcode_target" — "original" included) so the NEXT clip
        still gets offered "Same as original" first regardless of how THIS
        one resolved; "video_transcode_resolved_target" is the separate,
        already-concrete value actually used for THIS import."""
        dialog = ConvertedImportSettingsDialog(
            self.main_window, type_name, {
                "texture_import_format_mode": CONFIG.texture_import_format_mode,
                "texture_import_manual_format": CONFIG.texture_import_manual_format,
                "texture_import_quality": CONFIG.texture_import_quality,
                "texture_import_mipmaps": CONFIG.texture_import_mipmaps,
                "audio_import_quality": CONFIG.audio_import_quality,
                "video_transcode_target": CONFIG.video_transcode_target,
                "video_transcode_quality": CONFIG.video_transcode_quality,
            },
            platform=platform,
            version=version,
            source_file_path=source_file_path,
            obj=obj,
        )
        if exec_and_dispose(dialog) != QDialog.DialogCode.Accepted:
            return None
        values = dialog.get_values()
        kwargs = {
            "texture_quality": CONFIG.texture_import_quality,
            "texture_mipmaps": CONFIG.texture_import_mipmaps,
            "texture_format_mode": CONFIG.texture_import_format_mode,
            "texture_manual_format": CONFIG.texture_import_manual_format,
            "audio_quality": CONFIG.audio_import_quality,
        }
        for config_name, kwarg_name in (
            ("texture_import_format_mode", "texture_format_mode"),
            ("texture_import_manual_format", "texture_manual_format"),
            ("texture_import_quality", "texture_quality"),
            ("texture_import_mipmaps", "texture_mipmaps"),
            ("audio_import_quality", "audio_quality"),
            ("video_transcode_quality", "video_transcode_quality"),
        ):
            if config_name in values:
                setattr(CONFIG, config_name, values[config_name])
                kwargs[kwarg_name] = values[config_name]
        if "video_transcode_target" in values:
            # Persist the LITERAL choice ("original" included) so the combo
            # still defaults to it next time; pass the already-RESOLVED,
            # concrete target (computed by the dialog itself, see its own
            # _resolve_final_video_target()) to whatever actually runs the
            # transcode — these can legitimately differ for one single
            # import (a one-off fallback) without changing the standing
            # preference for the next one.
            CONFIG.video_transcode_target = values["video_transcode_target"]
            kwargs["video_transcode_target"] = values.get(
                "video_transcode_resolved_target", values["video_transcode_target"]
            )
        save_persisted_config()
        for key in ("video_transcode", "video_transcode_output_path"):
            if key in values:
                kwargs[key] = values[key]
        return kwargs

    def _import_patches_unscoped(self):
        texture_kwargs = self._resolve_bulk_texture_settings([], with_settings=False)
        self._import_patches_from_folder(
            self._gather_all_env_candidates, allow_sdf_mapping=True, **texture_kwargs
        )

    def _import_patches_from_folder(
        self, candidates_fn, *, allow_sdf_mapping: bool = False,
        texture_quality=None, texture_mipmaps=None, texture_format_mode=None, texture_manual_format=None,
        audio_quality=None, resource_target_mode=None, resource_name=None,
        backup_before_overwrite=None, backup_keep_latest=None,
        video_transcode=None, video_transcode_target=None, video_transcode_quality=None,
    ):
        """Shared by both folder-import entry points: pick a folder, match it
        against candidates_fn()'s (path_id, source, obj_ref) triples, confirm via
        ImportMatchDialog (pre-checked — see its own docstring for why this is the
        one place a confirmation dialog belongs, unlike single-file import), then
        run the patches as one queued IMPORT task.

        `allow_sdf_mapping` additionally enables on-the-fly SDF generation
        from a dropped sdf_map.txt (+ sibling chars.txt) — see
        _find_sdf_map_pairs()'s own docstring for the file layout. This runs
        ADDITIONALLY alongside dump/PNG patch matching, not as a fallback
        only tried when that finds nothing — a real folder can legitimately
        contain both. `False` (the default) is what import_patches_from_selection()/
        _with_settings() pass — a mapping file's own targets can name ANY
        object in the game, not just the ones the user actually selected, so
        this capability is deliberately withheld from the SELECTION-scoped
        entry points and only reachable through the whole-environment-scoped
        "Импорт в окружение..." action (_import_patches_unscoped), per the
        user's own explicit call on this exact risk."""
        win = self.main_window
        dir_path = QFileDialog.getExistingDirectory(win, tr("Выберите папку с патчами"))
        if not dir_path:
            return

        candidates = candidates_fn()
        if not candidates:
            win.log(tr("Нет объектов для сопоставления."), LogLevel.WARNING)
            return

        # texture_*/video_transcode* args are resolved by the caller (either
        # straight from CONFIG, or via a "...с настройками" dialog shown once
        # up front — see _resolve_bulk_texture_settings) since there's no
        # per-object dialog opportunity once a batch run like this is
        # underway. video_transcode_output_path is deliberately NOT one of
        # these params — match_patch_files() derives a correct per-object
        # output path next to each matched VideoClip's own patch file itself
        # (see its own docstring), the same way the CLI's `import` command
        # already relies on it.
        matches = match_patch_files(
            Path(dir_path), candidates,
            texture_quality=texture_quality,
            texture_mipmaps=texture_mipmaps,
            texture_format_mode=texture_format_mode,
            texture_manual_format=texture_manual_format,
            audio_quality=audio_quality,
            resource_target_mode=resource_target_mode,
            resource_name=resource_name,
            backup_before_overwrite=backup_before_overwrite,
            backup_keep_latest=backup_keep_latest,
            video_transcode=video_transcode,
            video_transcode_target=video_transcode_target,
            video_transcode_quality=video_transcode_quality,
        )

        # sdf_jobs: one core.sdf_map.SdfMapJob per sdf_map.txt that resolved to at least one target.
        # Kept separate per map: two maps in different subfolders can want different fonts/characters,
        # and a map's own conflict detection only ever applies within that one file.
        sdf_jobs = []
        if allow_sdf_mapping:
            from core.sdf_map import FontMapError, find_sdf_maps, load_sdf_map_jobs
            map_paths = find_sdf_maps(Path(dir_path))
            if map_paths:
                try:
                    sdf_jobs, sdf_warnings = load_sdf_map_jobs(map_paths, self._sdf_map_candidates_to_rows(candidates))
                except FontMapError as e:
                    QMessageBox.warning(win, tr("Импорт по карте SDF"), tr("Ошибка в карте SDF:\n{error}", error=e))
                    return
                for w in sdf_warnings:
                    win.log(w, LogLevel.WARNING)
                missing_fonts = sorted({str(m.font_path) for job in sdf_jobs for m in job.mappings
                                        if not m.font_path.is_file()})
                if missing_fonts:
                    QMessageBox.warning(
                        win, tr("Импорт по карте SDF"),
                        tr("Не найдены файлы шрифтов, указанные в карте SDF:") + "\n" + "\n".join(missing_fonts),
                    )
                    return

        # Same "nothing to process" case as before this feature existed —
        # if sdf_map.txt is absent entirely (or present but resolved to
        # nothing), this collapses to exactly the original condition/message.
        if not matches and not sdf_jobs:
            QMessageBox.information(win, tr("Импорт патчей"), tr("В выбранной папке не найдено подходящих файлов."))
            return

        if matches:
            self._run_folder_patch_import(dir_path, matches)
        if sdf_jobs:
            self._run_folder_sdf_map_import(sdf_jobs)

    def _run_folder_patch_import(self, dir_path: str, matches: list) -> None:
        """The dump/PNG patch-matching half of _import_patches_from_folder —
        unchanged behavior, just extracted so it can run independently of
        (and alongside) the new sdf_map.txt-driven generation below."""
        win = self.main_window
        # Not modal: the user can keep working in the table (select the objects a
        # mismatched patch was meant for and re-check) while the list stays open. It is
        # registered on the main window so loading new data or saving closes it — its
        # matches point into the loaded files. Only one at a time.
        previous = getattr(win, "import_match_dialog", None)
        if previous is not None:
            win.import_match_dialog = None
            previous.close()
        dialog = ImportMatchDialog(matches, win)
        dialog.setModal(False)
        win.import_match_dialog = dialog

        def on_finished(_result, dlg=dialog):
            if getattr(win, "import_match_dialog", None) is dlg:
                win.import_match_dialog = None
            dlg.deleteLater()

        def on_accepted(dlg=dialog):
            selected = dlg.selected_matches()
            if selected:
                self._start_folder_patch_import(dir_path, selected)

        dialog.accepted.connect(on_accepted)
        dialog.finished.connect(on_finished)
        dialog.show()

    def _start_folder_patch_import(self, dir_path: str, selected: list) -> None:
        """Queues the confirmed patches (see _run_folder_patch_import)."""
        win = self.main_window

        # If a folder contains BOTH a .resdata.bin file and a .dump.bin/.dump.json for
        # the SAME object (e.g. two separate exports of it taken at different times),
        # applying them in arbitrary filesystem order is a real footgun:
        # raw/json_dump replace the object's ENTIRE serialized record — including
        # its own m_Resource/m_StreamData offset+size fields — so if one of those
        # runs AFTER the content-raw import, it silently reverts the offset/size
        # content_raw just updated back to whatever that older snapshot had.
        # content_raw itself only ever patches offset/size against whatever the
        # object's CURRENT state is at apply-time (safe to run last, in any
        # relative order against other content_raw patches), so sorting it last
        # within the batch — a stable sort, so relative order is otherwise
        # unchanged — removes the dependency on enumeration order entirely.
        selected = sorted(selected, key=lambda p: p.mode == "content_raw")

        patched: list = []

        def fn(report_progress, should_cancel):
            total = len(selected)
            count = 0
            failed = 0
            pending_log = []
            throttle = ProgressThrottle()
            for i, patch in enumerate(selected):
                if should_cancel():
                    raise OperationCancelled()
                if throttle.should_report(i, total):
                    report_progress(i + 1, total, tr("Импорт... ({done}/{total})", done=i + 1, total=total), count, failed,
                                    pending_log)
                    pending_log = []
                    throttle.pause()
                try:
                    error = apply_matched_patch(patch)
                    if error and not error.startswith(IMPORT_WARNING_PREFIX):
                        failed += 1
                        pending_log.append(tr("Ошибка: {name} — {error}", name=patch.display_name, error=error))
                    else:
                        count += 1
                        patched.append(patch.obj)
                        if error:
                            pending_log.append(f"{patch.display_name} — {error[len(IMPORT_WARNING_PREFIX):]}")
                except Exception as e:
                    failed += 1
                    pending_log.append(tr("Ошибка: {name} — {error}", name=patch.display_name, error=e))
            report_progress(total, total, tr("Готово"), count, failed, pending_log)
            return self._format_bulk_result(tr("патчей"), count, total, Path(dir_path), operation="import")

        def on_success():
            # Not every patched obj has a table row (an "All Objects"-scope match
            # can be an object outside RICH_PREVIEW_TYPES) — build the reverse map
            # once rather than per-item; a one-off O(len(raw_data_list)) pass, not
            # a hot path (runs once per completed bulk import).
            #
            # Real bug found via a live test (a real folder-import round trip,
            # not just single-object imports, which never go through this
            # dict at all): ObjectReader is an attrs `@define`-generated class
            # with default eq=True, which per attrs' own documented behavior
            # sets __hash__ = None (unhashable) whenever eq=True and the class
            # isn't frozen — using it directly as a dict key raised
            # `TypeError: unhashable type: 'ObjectReader'`, immediately on the
            # very first completed bulk import that had ANY table row to
            # refresh. Keying by id(obj_ref) instead is not just a workaround
            # for the unhashability — it's the semantically correct choice
            # here anyway: this needs OBJECT IDENTITY ("is this the exact
            # ObjectReader instance we just patched"), not attrs' generated
            # field-by-field equality, which could spuriously match two
            # different objects with identical field values or fail to match
            # the same object once patch() has changed one of its fields.
            win2 = self.main_window
            # objects whose type the load left out were adopted by their patch: rows first (the save needs them)
            win2._add_rows_for_adopted(patched)
            by_obj = {id(item["obj_ref"]): item for item in win2.table_model.data_list}
            for obj in patched:
                item_data = by_obj.get(id(obj))
                if item_data is not None:
                    self._refresh_row_after_patch(item_data, obj)

        title = tr("Импорт патчей из папки")
        task_id = win.task_queue_manager.enqueue(TaskKind.IMPORT, title, fn)
        self._task_followups[task_id] = {"title": title, "on_success": on_success}

    def _run_folder_sdf_map_import(self, sdf_jobs: list) -> None:
        """The sdf_map.txt-driven half of _import_patches_from_folder. Each target's settings come
        from its own map line, then the map's `default:` line (both already merged into the
        ResolvedMapping by core.sdf_map), then — only if something is still unset — one dialog
        (SDFMapImportSettingsDialog). A map that fully specifies mode, size and range never
        shows the dialog. One queued IMPORT task then generates every target in sequence."""
        from core.sdf_map import FontMapError, SdfFallback, effective_settings
        win = self.main_window
        targets = [m for job in sdf_jobs for m in job.mappings]
        total_targets = len(targets)

        fallback = SdfFallback()
        if not all(m.is_fully_specified for m in targets):
            dialog = SDFMapImportSettingsDialog(win, len(sdf_jobs), total_targets)
            if exec_and_dispose(dialog) != QDialog.DialogCode.Accepted:
                return
            fallback = dialog.to_fallback()

        def fn(report_progress, should_cancel):
            total = len(targets)
            succeeded, failed = [], []
            for i, m in enumerate(targets):
                if should_cancel():
                    break
                name = get_row_name(m.row)
                report_progress(i, total, tr("Генерация SDF: {name}", name=name), 0, 0, [])
                try:
                    eff = effective_settings(m, fallback)
                except FontMapError as e:
                    # Surfaced per target (the rest of the batch continues), not as an abort.
                    failed.append(f"{name}: {e}")
                    continue
                try:
                    result = add_characters_to_font_asset(
                        m.row["obj_ref"], str(m.font_path), m.characters, mode=eff.mode,
                        point_size_override=eff.point_size, point_size_fit=eff.point_size_fit,
                        pxrange_override=eff.pxrange,
                        atlas_width_override=eff.atlas_width, atlas_height_override=eff.atlas_height,
                        match_original_height=eff.match_height,
                        include_existing_characters=eff.add_missing,
                    )
                except SDFGenerationError as e:
                    failed.append(f"{name}: {e}")
                    continue
                if result.added_count == 0:
                    failed.append(f"{name}: {result.summary_text()}")
                else:
                    succeeded.append(result.summary_text().splitlines()[0])
            report_progress(total, total, tr("Генерация SDF..."), 0, 0, [])

            if not succeeded and failed:
                raise RuntimeError(
                    tr("Не удалось сгенерировать SDF ни для одной из целей ({total}):", total=total)
                    + "\n" + "\n".join(failed)
                )
            lines = [tr("Готово: {count} из {total} целей.", count=len(succeeded), total=total)] + succeeded
            if failed:
                lines += ["", tr("Ошибки ({count}):", count=len(failed))] + failed
            return "\n".join(lines)

        def on_success():
            # Refresh every target regardless of success/failure: cheap and idempotent for a row
            # that wasn't touched, and it avoids threading per-item state back out of fn().
            for m in targets:
                self._refresh_sdf_font_rows(m.row, m.row["obj_ref"])

        title = tr("Импорт по карте SDF ({count} целей)", count=total_targets)
        task_id = win.task_queue_manager.enqueue(TaskKind.IMPORT, title, fn)
        self._task_followups[task_id] = {"title": title, "on_success": on_success}
