"""SDF font actions of ObjectActionsController: exporting one SDF font package or all of them, and generating
characters into one or several fonts (the SDF generator dialog).

Kept out of object_actions.py as a mixin (ObjectActionsController inherits it). Behaviour is unchanged; this is a
mechanical move (every method body is byte-identical to its old place in object_actions.py)."""

from core.i18n import tr, trn
import os
import tempfile

from PyQt6.QtWidgets import QFileDialog, QMessageBox

from config import CONFIG, LogLevel
from dialogs import SDFGeneratorDialog
from core.progress import OperationCancelled, ProgressThrottle
from core.object_preview import get_row_name
from core.sdf_resolver import build_sdf_groups, export_sdf_package, resolve_sdf_components, unique_sdf_folder_names
from core.sdf_generator import (
    SDFGenerationError, add_characters_to_font_asset, resolve_current_point_size, resolve_gradient_scale,
)
from task_queue import TaskKind
from gui_common import exec_and_dispose, export_target_dir


class SdfActionsMixin:
    def export_sdf_font(self, item_data: dict):
        """Exports a TMP_FontAsset's font/material/atlas texture together into
        one subfolder (core.sdf_resolver.export_sdf_package) — same
        type-appropriate per-component export as export_selected_object(),
        just bundled under one chosen folder instead of a separate save
        dialog per file. Resolution failures (a dangling material/texture
        reference) don't abort the export — whatever DID resolve still gets
        written, and the rest is reported as a skipped/missing line, mirroring
        export_object()'s own partial-success convention."""
        win = self.main_window
        obj = item_data["obj_ref"]
        components = resolve_sdf_components(obj)

        dir_path = QFileDialog.getExistingDirectory(win, tr("Выберите папку для экспорта SDF-шрифта"))
        if not dir_path:
            return
        base_dir = export_target_dir(dir_path)

        def fn(report_progress, should_cancel):
            out_dir, results = export_sdf_package(components, base_dir, overwrite=CONFIG.export_overwrite)
            lines = []
            failed = 0
            for r in results:
                if r.skipped:
                    lines.append("  " + tr("{part}: пропущено — {reason}", part=r.label, reason=r.message))
                elif r.message:
                    failed += 1
                    lines.append("  " + tr("{part}: ошибка — {error}", part=r.label, error=r.message))
                else:
                    lines.append(f"  {r.label}: {r.out_path}")
            if failed == len(results):
                raise RuntimeError(tr("Не удалось экспортировать ни один из компонентов SDF-шрифта:") + "\n"
                                   + "\n".join(lines))
            return tr("Экспортирован SDF-пакет в {folder}", folder=out_dir)

        title = get_row_name(item_data)
        task_id = win.task_queue_manager.enqueue(TaskKind.EXPORT, title, fn)
        self._task_followups[task_id] = {
            "title": title, "folder": base_dir, "on_success": lambda: self._maybe_open_folder(base_dir),
        }

    def export_all_sdf_fonts(self):
        """Bulk counterpart to export_sdf_font() — every SDF font package
        currently in SDF Viewer Mode's tree (win.sdf_group_model.groups, built
        by main.py's _refresh_sdf_groups()), each into its own subfolder under
        one chosen base folder, same as exporting them one at a time would
        produce. Wired to the "Экспортировать все SDF шрифты..." button that
        replaces the search bar while that mode is active (see main.py's
        set_sdf_mode()) — there's no per-row selection driving this, so it
        isn't reachable via _build_single_item_menu()/_show_bulk_context_menu()
        the way every other export action here is.

        Re-resolves each font's components fresh (resolve_sdf_components)
        rather than reusing whatever SDFGroup.material/texture ended up
        being — those are display RowItems (possibly synthesized ones for a
        component that isn't a real table row, see build_sdf_groups()), not
        the SDFComponents shape export_sdf_package() needs."""
        win = self.main_window
        # The tree model is only populated while SDF Viewer Mode is active
        # (main.py's _refresh_sdf_groups()), but this action is ALSO reachable from
        # the normal table's context menu ("Экспортировать SDF → Все шрифты") —
        # real report: from there it always said no SDF fonts were found. Build
        # the groups from the table directly when the tree has none.
        groups = list(win.sdf_group_model.groups) or build_sdf_groups(win.raw_data_list)
        if not groups:
            win.log(tr("Нет обнаруженных SDF-шрифтов для экспорта."), LogLevel.WARNING)
            return

        dir_path = QFileDialog.getExistingDirectory(win, tr("Выберите папку для экспорта всех SDF-шрифтов"))
        if not dir_path:
            return
        base_dir = export_target_dir(dir_path)
        # Real reported concern: two SDF fonts can share the same name (a "Fallback" variant, the
        # same font shipped for two languages, ...) — without this, the second one's export would
        # silently land in and overwrite the first's folder. Only the names that actually collide
        # in THIS batch get a disambiguating suffix — see unique_sdf_folder_names()'s own docstring.
        folder_names = unique_sdf_folder_names(groups)

        def fn(report_progress, should_cancel):
            total = len(groups)
            count = 0
            failed = 0
            pending_log = []
            throttle = ProgressThrottle()
            for i, group in enumerate(groups):
                if should_cancel():
                    raise OperationCancelled()
                if throttle.should_report(i, total):
                    report_progress(i + 1, total, tr("Экспорт SDF-шрифтов... ({done}/{total})", done=i + 1, total=total),
                                    count, failed, pending_log)
                    pending_log = []
                    throttle.pause()

                font_name = get_row_name(group.font)
                try:
                    components = resolve_sdf_components(group.font["obj_ref"])
                    out_dir, results = export_sdf_package(
                        components, base_dir, overwrite=CONFIG.export_overwrite,
                        folder_name=folder_names.get(group.group_id),
                    )
                    item_failed = sum(1 for r in results if not r.skipped and r.message)
                    if item_failed == len(results):
                        failed += 1
                        pending_log.append(tr("Ошибка: {name} — ни один компонент не экспортирован", name=font_name))
                    else:
                        count += 1
                        if item_failed:
                            pending_log.append(tr("Частично: {name} — не удалось компонентов: {count}",
                                                  name=font_name, count=item_failed))
                except Exception as e:
                    failed += 1
                    pending_log.append(tr("Ошибка: {name} — {error}", name=font_name, error=e))
            report_progress(total, total, tr("Готово"), count, failed, pending_log)
            return self._format_bulk_result(tr("SDF-шрифтов"), count, total, base_dir)

        title = tr("Экспорт всех SDF-шрифтов")
        task_id = win.task_queue_manager.enqueue(TaskKind.EXPORT, title, fn)
        self._task_followups[task_id] = {
            "title": title, "folder": base_dir, "on_success": lambda: self._maybe_open_folder(base_dir),
        }

    def _refresh_sdf_font_rows(self, item_data: dict, obj) -> None:
        """Shared by generate_sdf_font()'s and generate_sdf_font_multi()'s
        own on_success — a successful generation patches TWO objects (the
        font asset itself, and its atlas Texture2D's new pixel data), so
        both rows need refreshing, not just the one the user clicked.
        Matches build_sdf_groups()'s own (source, path_id) lookup convention
        for finding an already-indexed row (Python object identity isn't
        reliable across a reload — see that function's own docstring)."""
        win = self.main_window
        self._refresh_row_after_patch(item_data, obj)
        components = resolve_sdf_components(obj)
        if components.texture_obj is None:
            return
        tex_source = components.texture_obj.assets_file.name if components.texture_obj.assets_file else None
        tex_path_id = components.texture_obj.path_id
        for row_item in win.table_model.data_list:
            if row_item.get("source") == tex_source and row_item.get("path_id") == tex_path_id:
                self._refresh_row_after_patch(row_item, components.texture_obj)
                break

    def generate_sdf_font(self, item_data: dict):
        """Adds new characters to a TMP_FontAsset's existing SDF atlas — see
        core/sdf_generator.py for the actual generation (msdf-atlas-gen +
        the verified unit-conversion formula + atlas compositing). SDF-only
        for now (no MSDF option offered — stock TMP has no shader that can
        decode it, see that module's own docstring).

        Pre-fills the font-file field from the asset's own embedded
        m_SourceFontFile when one is linked (most shipped "static" font
        assets strip this to save build size, so it's routinely absent —
        the dialog just starts with an empty field in that case, same as
        every converted-import dialog already does when there's nothing to
        default to).

        Generation itself now runs INSIDE SDFGeneratorDialog (show_preview=True
        — Unity Font Asset Creator-style Generate-then-inspect-then-Save/
        Cancel, see that dialog's own module docstring), not via this
        controller's task queue: by the time .exec() returns Accepted, the
        new atlas has already been built (auto_commit=False — nothing
        written yet) and the user has already reviewed it. This method's own
        job shrinks to resolving the CURRENT point size/pxrange to show as
        "Как в оригинале", and — only once actually accepted — calling
        result.commit() (fast: in-memory patch() calls, no subprocess, so no
        need for the background task queue at this point) and refreshing the
        table rows exactly as the old on_success callback did."""
        win = self.main_window
        obj = item_data["obj_ref"]
        components = resolve_sdf_components(obj)
        if components.texture_obj is None:
            QMessageBox.warning(
                win, tr("Генерация SDF"),
                tr("Не удалось найти текстуру атласа для этого шрифта: {error}", error=components.texture_error),
            )
            return

        default_font_path = ""
        temp_font_path = None
        if components.source_font_obj is not None:
            try:
                font_data = components.source_font_obj.read()
                raw = bytes(font_data.m_FontData) if font_data.m_FontData else b""
                if raw:
                    ext = ".otf" if raw[:4] == b"OTTO" else ".ttf"
                    fd, temp_font_path = tempfile.mkstemp(suffix=ext, prefix="ustudio_sdf_src_")
                    with os.fdopen(fd, "wb") as f:
                        f.write(raw)
                    default_font_path = temp_font_path
            except Exception:
                pass

        try:
            current_point_size = resolve_current_point_size(obj.parse_as_dict())
        except Exception:
            current_point_size = None
        current_pxrange = resolve_gradient_scale(components.material_obj)

        font_name = get_row_name(item_data)
        dialog = SDFGeneratorDialog(
            win, font_name, default_font_path,
            current_point_size=current_point_size, current_pxrange=current_pxrange,
            font_obj=obj, show_preview=True,
        )
        try:
            accepted = exec_and_dispose(dialog)
        finally:
            # The temp file's lifetime now spans the WHOLE dialog session
            # (the user may click "Генерировать" more than once with
            # different settings before ever saving) rather than one single
            # generation call — cleaned up once, here, regardless of how many
            # times generation ran inside the dialog or whether it was ever
            # accepted at all.
            if temp_font_path:
                try:
                    os.remove(temp_font_path)
                except OSError:
                    pass

        # Take what's needed, then let go of the dialog: it's parented to the main
        # window, so merely leaving this scope doesn't destroy it, and it would
        # keep this font's ObjectReader and the result's commit() closure alive
        # for the whole session. release_references() breaks those references now
        # (deleteLater() alone isn't reliable for that — see main.py's
        # _close_dialogs_before_env_teardown); deleteLater() then frees the widget.
        result = dialog.get_result() if accepted else None
        dialog.release_references()
        dialog.deleteLater()
        del dialog

        if not accepted:
            return
        if result is None or result.added_count == 0:
            return

        try:
            result.commit()
        except Exception as e:
            win.log(tr("Ошибка сохранения SDF для «{name}»: {error}", name=font_name, error=e), LogLevel.ERROR)
            return

        win.log(result.summary_text())
        self._refresh_sdf_font_rows(item_data, obj)

    def generate_sdf_font_multi(self, font_items: list):
        """Multi-row-selection counterpart to generate_sdf_font() — the SAME
        font file, character set, and mode applied to every selected
        TMP_FontAsset in one batch (real reported request: adding e.g.
        Cyrillic to every font in a game one-at-a-time didn't scale). Each
        font asset is still generated independently via the same
        add_characters_to_font_asset() the single-font action uses — its own
        schema (modern/legacy), atlas, and existing glyphs are read fresh
        per object, so a batch can freely mix font assets on different
        schemas/games without any special-casing here.

        Deliberately never pre-fills from an embedded source font the way
        generate_sdf_font() does for a single object — a batch can span
        several font assets with DIFFERENT (or no) embedded fonts, and
        defaulting to any ONE of them would be a misleading guess for the
        others. The user always picks/confirms one real file for the whole
        batch, same as generate_sdf_font()'s own no-embedded-font case."""
        win = self.main_window
        if not font_items:
            return

        display_name = (get_row_name(font_items[0]) if len(font_items) == 1
                        else trn(len(font_items), "{n} шрифт", "{n} шрифта", "{n} шрифтов"))
        # varies_per_object=True: each selected font asset keeps its OWN
        # point size/pxrange under "Как в оригинале" — there's no single
        # shared "current" value across a batch to show (see
        # _SizeOverrideGroup's own docstring for why this differs from the
        # single-object dialog). "Свой" still applies the SAME custom value
        # to every font in the batch, exactly like characters/mode already do.
        dialog = SDFGeneratorDialog(win, display_name, default_font_path="", varies_per_object=True)
        accepted = exec_and_dispose(dialog)
        if accepted:
            font_path = dialog.get_font_path()
            characters = dialog.get_characters()
            mode = dialog.get_mode()
            point_size_override = dialog.get_point_size_override()
            point_size_fit = dialog.get_point_size_fit()
            match_original_height = dialog.get_match_height()
            pxrange_override = dialog.get_pxrange_override()
            add_missing = dialog.get_add_missing()
        # Parented to the main window, so it isn't destroyed by going out of scope —
        # same cleanup as generate_sdf_font() (this one holds no font object, but
        # there's no reason to leave a finished modal dialog lingering per batch).
        dialog.release_references()
        dialog.deleteLater()
        del dialog
        if not accepted:
            return

        def fn(report_progress, should_cancel):
            total = len(font_items)
            succeeded, failed = [], []
            for i, item in enumerate(font_items):
                if should_cancel():
                    break
                name = get_row_name(item)
                report_progress(i, total, tr("Генерация SDF: {name}", name=name), 0, 0, [])
                try:
                    result = add_characters_to_font_asset(
                        item["obj_ref"], font_path, characters, mode=mode,
                        point_size_override=point_size_override, point_size_fit=point_size_fit,
                        pxrange_override=pxrange_override, match_original_height=match_original_height,
                        include_existing_characters=add_missing,
                    )
                except SDFGenerationError as e:
                    failed.append(f"{name}: {e}")
                    continue
                if result.added_count == 0:
                    failed.append(f"{name}: {result.summary_text()}")
                else:
                    # summary_text()'s own first line already reads "«name»:
                    # добавлено X из Y символов." — reused as-is instead of
                    # a second, independent "{name}: added X of Y" phrasing
                    # that would only drift from it over time.
                    succeeded.append(result.summary_text().splitlines()[0])
            report_progress(total, total, tr("Генерация SDF..."), 0, 0, [])

            if not succeeded:
                raise RuntimeError(
                    tr("Не удалось сгенерировать SDF ни для одного из шрифтов ({total}):", total=total)
                    + "\n" + "\n".join(failed)
                )
            lines = [tr("Готово: {count} из {total} шрифтов.", count=len(succeeded), total=total)] + succeeded
            if failed:
                lines += ["", tr("Ошибки ({count}):", count=len(failed))] + failed
            return "\n".join(lines)

        def on_success():
            for item in font_items:
                self._refresh_sdf_font_rows(item, item["obj_ref"])

        title = tr("Генерация SDF ({count} шрифтов)", count=len(font_items))
        task_id = win.task_queue_manager.enqueue(TaskKind.IMPORT, title, fn)
        self._task_followups[task_id] = {"title": title, "on_success": on_success}
