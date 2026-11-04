"""Exports of ObjectActionsController: one object (converted / raw / content), JSON dumps, and the queued bulk
exports (selection, select-all, every object of a script or type) with their grouped log lines.

Kept out of object_actions.py as a mixin (ObjectActionsController inherits it). Behaviour is unchanged; this is a
mechanical move (every method body is byte-identical to its old place in object_actions.py)."""

from core.i18n import tr
import os
from pathlib import Path
from typing import Optional, Tuple

from PyQt6.QtWidgets import QFileDialog

from config import CONFIG, LogLevel
from core.progress import OperationCancelled, ProgressThrottle
from core.object_preview import (
    build_export_json, build_export_stem, export_object, export_object_content_raw, export_object_raw, get_row_name,
    get_row_script_name, sanitize_export_filename,
)
from core.file_utils import peek_mb_identity, safe_join
from task_queue import LogNote, TaskKind
from gui_common import export_target_dir


# _make_bulk_export_fn's own grouped-log-line cap — same convention/wording as
# core.sdf_generator's _MAX_LISTED_CODEPOINTS ("Пропущено N: name1, name2, ...
# и ещё M — причина"), reused here rather than reinvented.
_MAX_GROUPED_LOG_NAMES = 8


class ExportActionsMixin:
    def export_raw_single(self, item_data: dict):
        """"Экспортировать как Raw..." — the object's own serialized bytes
        (export_object_raw), a deliberate, always-available choice distinct from
        export_selected_object()'s type-converted attempt."""
        win = self.main_window
        obj = item_data["obj_ref"]
        dir_path = QFileDialog.getExistingDirectory(win, tr("Выберите папку для экспорта"))
        if not dir_path:
            return
        out_dir = export_target_dir(dir_path)

        def fn(report_progress, should_cancel):
            out_path, message = export_object_raw(obj, out_dir)
            if message:
                raise RuntimeError(message)
            return tr("Экспортирован Raw: {path}", path=out_path)

        title = get_row_name(item_data)
        task_id = win.task_queue_manager.enqueue(TaskKind.EXPORT, title, fn)
        self._task_followups[task_id] = {
            "title": title, "folder": out_dir, "on_success": lambda: self._maybe_open_folder(out_dir),
        }

    def export_content_raw_single(self, item_data: dict):
        """"Содержимое (Raw)" — the external resource's own bytes for a resource-
        backed type (Texture2D/Texture2DArray/AudioClip/Mesh/VideoClip), as opposed
        to the object's own small header record."""
        win = self.main_window
        obj = item_data["obj_ref"]
        dir_path = QFileDialog.getExistingDirectory(win, tr("Выберите папку для экспорта"))
        if not dir_path:
            return
        out_dir = export_target_dir(dir_path)

        def fn(report_progress, should_cancel):
            out_path, message, skipped = export_object_content_raw(obj, out_dir)
            if skipped:
                return tr("Пропущено: {reason}", reason=message)
            if message:
                raise RuntimeError(message)
            return tr("Экспортировано содержимое: {path}", path=out_path)

        title = get_row_name(item_data)
        task_id = win.task_queue_manager.enqueue(TaskKind.EXPORT, title, fn)
        self._task_followups[task_id] = {
            "title": title, "folder": out_dir, "on_success": lambda: self._maybe_open_folder(out_dir),
        }

    def export_selected_object(self, item_data: dict):
        """Type-appropriate export (image/audio/text/mesh/... via
        core.object_preview.export_object, JSON fallback for everything else) —
        additive next to dump_single_object, which stays as the explicit
        always-JSON option regardless of type."""
        win = self.main_window
        obj = item_data["obj_ref"]

        dir_path = QFileDialog.getExistingDirectory(win, tr("Выберите папку для экспорта"))
        if not dir_path:
            return
        out_dir = export_target_dir(dir_path)

        def fn(report_progress, should_cancel):
            out_path, message, skipped = export_object(obj, out_dir, overwrite=CONFIG.export_overwrite)
            if skipped:
                # Not a real error (see export_object()'s docstring) — an
                # empty texture, a Font with no embedded data, etc. Report it
                # plainly rather than failing the task over it.
                return tr("Пропущено: {reason}", reason=message)
            if message:
                raise RuntimeError(message)
            return tr("Экспортирован объект: {path}", path=out_path)

        title = get_row_name(item_data)
        task_id = win.task_queue_manager.enqueue(TaskKind.EXPORT, title, fn)
        self._task_followups[task_id] = {
            "title": title, "folder": out_dir, "on_success": lambda: self._maybe_open_folder(out_dir),
        }

    def dump_single_object(self, item_data):
        """Folder-picker dialog, same convention as every other export action in
        this file (export_selected_object/export_raw_single/export_sdf_font/...) —
        writes {build_export_stem(obj)}.dump.json into the chosen folder."""
        win = self.main_window
        obj = item_data["obj_ref"]

        dir_path = QFileDialog.getExistingDirectory(win, tr("Выберите папку для экспорта"))
        if not dir_path:
            return
        out_dir = export_target_dir(dir_path)

        def fn(report_progress, should_cancel):
            # is_partial ignored here — either way (genuinely unreadable, or
            # readable-but-only-partially) nothing gets written and err already
            # explains which (see build_export_json()'s own docstring for why a
            # partial parse is refused rather than silently exported).
            text, err, _is_partial = build_export_json(obj)
            if text is None:
                raise RuntimeError(err)
            out_path = safe_join(out_dir, f"{build_export_stem(obj)}.dump.json")
            # Real reported bug: a string field decoded via errors="surrogateescape"
            # (any binary-ish TextAsset content, or a similar field elsewhere) can
            # contain lone surrogate codepoints that the default strict UTF-8 codec
            # refuses to encode ("'utf-8' codec can't encode character '\udcXX':
            # surrogates not allowed") — and since open(..., "w") already
            # creates/truncates the file before write() ever runs, that raised
            # exception left an empty file behind. Encoding to bytes FIRST (same
            # surrogateescape codec export_object()'s own TextAsset branch already
            # uses for exactly this kind of data) means a bad string can't crash
            # AND can't leave a partial/empty file — nothing touches disk until the
            # encode has already succeeded.
            data = text.encode("utf-8", errors="surrogateescape")
            with open(out_path, "wb") as f:
                f.write(data)
            return tr("Экспортирован дамп: {path}", path=out_path)

        title = get_row_name(item_data)
        task_id = win.task_queue_manager.enqueue(TaskKind.EXPORT, title, fn)
        self._task_followups[task_id] = {
            "title": title,
            "folder": out_dir,
            "on_success": lambda: self._maybe_open_folder(out_dir),
        }

    # --- Bulk JSON dump (queued, with real progress) — shared by dump-by-script
    # and the multi-row-selection export below ---

    @staticmethod
    def _format_bulk_result(
        kind_word: str, count: int, total: int, out_dir: Path, skipped: int = 0, operation: str = "export",
    ) -> str:
        """kind_word: what was exported/imported, genitive plural for the
        Russian phrasing below — "дампов"/"объектов"/"патчей". `operation`
        picks which verb set to use — "export" (default, every export path)
        or "import" (the one folder-import path that reuses this same
        formatter for its own summary). Real reported bug: this always said
        "Экспорт..." even when called from _import_patches_from_folder()'s
        import-result summary — "Экспорт завершён успешно: 1 патчей в ..."
        after a successful IMPORT, confusingly implying the wrong operation
        happened. Every export call site already relied on the default, so
        adding this parameter (rather than, say, a second near-duplicate
        formatter) couldn't change any of their existing wording.

        Real reported request: "N из M" phrasing reads the same regardless of
        whether anything actually failed, which left even a fully successful
        bulk run looking like a partial result at a glance (count == total is
        easy to miss in a long log line) — worth calling out explicitly
        instead of leaving the user to notice the two numbers happen to
        match. A genuine partial result keeps the "N из M" framing (still
        accurate — some really are missing) and now also says outright how
        many failed, so it doesn't read as merely a smaller total.

        `count` here means files ACTUALLY WRITTEN — skipped items (an empty
        texture, a Font with no embedded data, ...) are passed separately via
        `skipped`, not folded into `count`. Real reported bug: they used to be
        counted as "succeeded" since nothing technically went wrong, which
        produced a genuinely misleading summary — "Экспорт завершён успешно:
        110 объектов" while the log's own per-item notes showed some were
        skipped, i.e. fewer than 110 files actually landed on disk. `count +
        skipped == total` with no real failures is now reported as its own
        distinct, still non-alarming outcome rather than silently rounded up
        to "successfully"."""
        failed = total - count - skipped
        kw = dict(count=count, total=total, kind=kind_word, folder=out_dir, skipped=skipped, failed=failed)
        if operation == "import":
            if failed <= 0 and skipped <= 0:
                return tr("Импорт завершён успешно: {total} {kind} из {folder}", **kw)
            if failed <= 0:
                return tr("Импорт завершён: {count} {kind} из {folder} ({skipped} пропущено)", **kw)
            if skipped:
                return tr("Импортировано {count} из {total} {kind} из {folder} ({failed} не удалось обработать, "
                          "{skipped} пропущено)", **kw)
            return tr("Импортировано {count} из {total} {kind} из {folder} ({failed} не удалось обработать)", **kw)
        if failed <= 0 and skipped <= 0:
            return tr("Экспорт завершён успешно: {total} {kind} в {folder}", **kw)
        if failed <= 0:
            return tr("Экспорт завершён: {count} {kind} в {folder} ({skipped} пропущено)", **kw)
        if skipped:
            return tr("Экспортировано {count} из {total} {kind} в {folder} ({failed} не удалось обработать, "
                      "{skipped} пропущено)", **kw)
        return tr("Экспортировано {count} из {total} {kind} в {folder} ({failed} не удалось обработать)", **kw)

    @staticmethod
    def _grouped_out_dir(base_dir: Path, item: dict) -> Path:
        """ExportSettingsDialog's grouping mode ("none"/"type"/"source") —
        applied per item since a bulk export's items can span several types/
        sources at once. Creates the subfolder on first use (base_dir itself
        is already guaranteed to exist by the caller)."""
        mode = CONFIG.export_grouping
        if mode == "type":
            subdir = sanitize_export_filename(str(item.get("type", "")), fallback="unknown_type")
        elif mode == "source":
            subdir = sanitize_export_filename(str(item.get("source", "")), fallback="unknown_source")
        else:
            return base_dir
        target = base_dir / subdir
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _maybe_open_folder(self, out_dir: Path) -> None:
        """ExportSettingsDialog's "Открывать папку после экспорта" — best-effort,
        wired as a queued task's on_success follow-up (see _on_task_finished)
        so it only runs once the export actually succeeded."""
        if not CONFIG.export_open_folder_after or not Path(out_dir).exists():
            return  # nothing to show (e.g. every item was skipped and the empty folder was pruned)
        try:
            os.startfile(str(out_dir))
        except OSError as e:
            self.main_window.log(tr("Не удалось открыть папку {folder}: {error}", folder=out_dir, error=e),
                                 LogLevel.WARNING)

    def _export_one_item(self, obj, item_out_dir: Path, mode: str) -> Tuple[str, Optional[str]]:
        """Exports one object per `mode`, normalized to (status, note) where status
        is "ok"/"skipped"/"error" — the one place every bulk export loop below
        dispatches to, so export_selected_objects/dump_multiple_objects_json/
        dump_by_script_type/export_type_objects_as only differ in which items they
        gather, never in how a single item gets exported."""
        if mode == "converted":
            _out_path, message, skipped = export_object(obj, item_out_dir, overwrite=CONFIG.export_overwrite)
            if skipped:
                return "skipped", message
            return ("error", message) if message else ("ok", None)

        if mode == "json_dump":
            text, err, is_partial = build_export_json(obj)
            if text is None:
                # A partial parse is an expected "nothing usable to write" case
                # (see build_export_json()'s own docstring), same category as an
                # empty texture — counted as skipped, not failed, so bulk stats
                # don't lump it in with a genuine per-object error.
                if is_partial:
                    return "skipped", err
                return "error", err or tr("не удалось прочитать объект")
            out_path = safe_join(item_out_dir, f"{build_export_stem(obj)}.dump.json")
            if not CONFIG.export_overwrite and out_path.exists():
                return "skipped", tr("файл уже существует: {name}", name=out_path.name)
            # Same surrogateescape fix as dump_single_object() above — a string
            # field decoded from binary-ish content can contain lone surrogates
            # the strict UTF-8 codec refuses to encode; encoding to bytes first
            # also means a bad string can't leave a partial/empty file behind.
            with open(out_path, "wb") as f:
                f.write(text.encode("utf-8", errors="surrogateescape"))
            return "ok", None

        if mode == "raw":
            _out_path, message = export_object_raw(obj, item_out_dir)
            return ("error", message) if message else ("ok", None)

        if mode == "content_raw":
            _out_path, message, skipped = export_object_content_raw(obj, item_out_dir)
            if skipped:
                return "skipped", message
            return ("error", message) if message else ("ok", None)

        return "error", f"Неизвестный режим экспорта: {mode}"  # i18n: keep (a programming error)

    @staticmethod
    def _flush_grouped_notes(target_log: list, groups: dict, kind: str) -> None:
        """Turns {reason: [item_name, ...]} into one LogNote per reason (see
        task_queue.LogNote) and empties `groups`. Real reported problem: a bulk
        run where dozens of objects share one skip/error reason logged a full
        line per item. Only the first few names travel with the note; the
        panel merges notes with the same reason across the whole task."""
        for reason, names in groups.items():
            target_log.append(LogNote(kind, reason, len(names), tuple(names[:_MAX_GROUPED_LOG_NAMES])))
        groups.clear()

    def _make_bulk_export_fn(self, items: list, out_dir: Path, mode: str, kind_word: str):
        """Returns a queue task fn that exports every item in `items` into out_dir
        via _export_one_item(obj, ..., mode), with real progress and per-item error
        tolerance — the shared work behind every bulk export action in this file."""
        def _run(report_progress, should_cancel):
            out_dir.mkdir(parents=True, exist_ok=True)
            total = len(items)
            count = 0
            skipped = 0
            failed = 0
            # Batched locally and flushed to the task at the SAME throttled
            # cadence as everything else (never one report_progress call per
            # item — see task_queue.TaskFn's docstring on why) — shown in the
            # queue panel's own "Журнал" tab, not the main app log. Skip/error
            # notes are grouped by reason WITHIN each flush window (not across
            # the whole task) via _flush_grouped_notes() — this keeps
            # cancellation behavior unchanged (whatever accumulated since the
            # last flush is still lost on cancel, exactly as before this
            # change; nothing here adds a new flush-on-cancel guarantee that
            # didn't already exist) while still collapsing runs of
            # identical-reason items into one line per window instead of one
            # per item.
            pending_log = []
            pending_skips: dict = {}
            pending_errors: dict = {}
            # Throttle progress/pause by TIME, not by object count — otherwise
            # overhead grows linearly with dataset size (see ProgressThrottle's
            # docstring in core/progress.py).
            throttle = ProgressThrottle()

            for i, item in enumerate(items):
                if should_cancel():
                    raise OperationCancelled()
                if throttle.should_report(i, total):
                    self._flush_grouped_notes(pending_log, pending_skips, "skipped")
                    self._flush_grouped_notes(pending_log, pending_errors, "error")
                    report_progress(i + 1, total, tr("Экспорт... ({done}/{total})", done=i + 1, total=total), count, failed,
                                    pending_log)
                    pending_log = []
                    throttle.pause()

                obj = item["obj_ref"]
                item_name = get_row_name(item)
                try:
                    item_out_dir = self._grouped_out_dir(out_dir, item)
                    status, note = self._export_one_item(obj, item_out_dir, mode)
                    if status == "ok":
                        count += 1
                    elif status == "skipped":
                        # Not a real error (see export_object()'s docstring) — an
                        # empty texture, a Font with no embedded data, a resource-
                        # backed object with no external resource, etc. — but NOT
                        # counted as a success either: nothing was actually
                        # written, so it must not inflate the "succeeded" count
                        # _format_bulk_result reports (see its own docstring for
                        # the real bug this fixes).
                        skipped += 1
                        pending_skips.setdefault(note or tr("без указанной причины"), []).append(item_name)
                    else:
                        failed += 1
                        pending_errors.setdefault(note or tr("без указанной причины"), []).append(item_name)
                except Exception as e:
                    failed += 1
                    pending_errors.setdefault(str(e), []).append(item_name)
                    continue
            self._flush_grouped_notes(pending_log, pending_skips, "skipped")
            self._flush_grouped_notes(pending_log, pending_errors, "error")
            report_progress(total, total, tr("Готово"), count, failed, pending_log)
            return self._format_bulk_result(kind_word, count, total, out_dir, skipped=skipped)

        def fn(report_progress, should_cancel):
            # Real report: an empty "MonoBehaviour_<script>" folder was left behind
            # when nothing was exported (every object skipped/failed, or cancelled).
            # The folders are created up front, so remember what did not exist yet
            # and remove whatever of it is still empty afterwards — on every exit
            # path. Folders that already existed, and anything containing a file,
            # are never touched.
            missing_chain = []
            p = out_dir
            while not p.exists() and p != p.parent:
                missing_chain.append(p)
                p = p.parent
            subdirs_before = {c for c in out_dir.iterdir() if c.is_dir()} if out_dir.exists() else set()
            try:
                return _run(report_progress, should_cancel)
            finally:
                self._prune_new_empty_dirs(out_dir, subdirs_before, missing_chain)
        return fn

    @staticmethod
    def _prune_new_empty_dirs(out_dir: Path, subdirs_before: set, missing_chain: list) -> None:
        try:
            if out_dir.exists():
                # _grouped_out_dir only ever creates IMMEDIATE children of out_dir, so
                # only those are candidates (never anything deeper that already existed).
                for d in out_dir.iterdir():
                    if d.is_dir() and d not in subdirs_before:
                        try:
                            d.rmdir()  # only succeeds when empty
                        except OSError:
                            pass
            for d in missing_chain:  # deepest first: out_dir, then any parents made for it
                try:
                    d.rmdir()
                except OSError:
                    break
        except OSError:
            pass

    def _run_bulk_export(self, items: list, mode: str, kind_word: str, title: str):
        """Folder-picker + enqueue, shared by every bulk export entry point that
        doesn't need a custom output subfolder name (dump_by_script_type builds its
        own "MonoBehaviour_{script}" folder and so calls _make_bulk_export_fn
        directly instead of through this)."""
        win = self.main_window
        if not items:
            return
        dir_path = QFileDialog.getExistingDirectory(win, tr("Выберите папку для экспорта"))
        if not dir_path:
            return
        out_dir = export_target_dir(dir_path)
        task_id = win.task_queue_manager.enqueue(
            TaskKind.EXPORT, title, self._make_bulk_export_fn(items, out_dir, mode, kind_word)
        )
        self._task_followups[task_id] = {
            "title": title, "folder": out_dir, "on_success": lambda: self._maybe_open_folder(out_dir),
        }

    def dump_by_script_type(self, target_item, mode: str = "json_dump"):
        """Exports every object that has the same script as `target_item`, as JSON dumps (default) or Raw."""
        win = self.main_window

        # Resolve the target row's FULL script identity (class name +
        # namespace + assembly), not just its bare class name — "every
        # object with THIS script" must mean exactly that, even when a
        # different, unrelated class happens to share the same bare name
        # (a real, confirmed-plausible case: third-party Unity packages
        # routinely define a class like "SaveSystem"/"Bloom" under their own
        # namespace, and a user's own game code can define a different class
        # with the identical bare name — see
        # core.object_common.script_checklist_entries()'s own docstring).
        # Comparing two ScriptIdentity instances directly (a frozen,
        # equality-comparable dataclass) is exact — no string-selector
        # ambiguity to resolve, unlike row_matches_script_selector() (used
        # for a user-TYPED name, where that ambiguity is unavoidable).
        obj_ref = target_item.get("obj_ref")
        identity = peek_mb_identity(obj_ref) if obj_ref is not None else None
        if identity is not None and identity.class_name != "Unknown":
            script_name = identity.class_name
        else:
            # No object to resolve a full identity from (an older/other
            # caller shape, or resolution genuinely failed) — fall back to
            # the previous bare-name-only behavior rather than finding
            # nothing. target_item["script_name"] for a real RowItem (this
            # table's own context menu) — lazily resolved, see
            # get_row_script_name() — falls back to target_item["name"] for
            # text_search_tool.py's separate match_data dicts, which
            # resolve "name" to the script name for a MonoBehaviour match
            # (see that file's names_cache construction). The "script_name"
            # in target_item check (not a truthiness check) is what tells
            # the two shapes apart: only a real RowItem has that key at
            # all, whether or not it's been resolved yet.
            if "script_name" in target_item:
                script_name = str(get_row_script_name(target_item) or "").strip()
            else:
                script_name = str(target_item.get("name", "")).strip()

        dir_path = QFileDialog.getExistingDirectory(win, tr("Выберите папку для экспорта"))
        if not dir_path:
            return

        safe_dirname = sanitize_export_filename(script_name, fallback="unknown_script")
        export_dir = export_target_dir(dir_path) / f"MonoBehaviour_{safe_dirname}"
        # win.raw_data_list is always real RowItems regardless of which caller
        # (main table or text_search_tool) triggered this — always has script_name.
        # This is exactly the "user explicitly asked to find every object of
        # this script" bulk case get_row_script_name()'s laziness expects to
        # pay for on demand — same as sorting/filtering by that column.
        if identity is not None and identity.class_name != "Unknown":
            items = [
                item for item in win.raw_data_list
                if item.get("type") == "MonoBehaviour" and peek_mb_identity(item.get("obj_ref")) == identity
            ]
        else:
            items = [item for item in win.raw_data_list if get_row_script_name(item).strip() == script_name]

        if not items:
            win.log(tr("Не найдено объектов со скриптом «{script}» для экспорта.", script=script_name), LogLevel.WARNING)
            return

        kind_word = tr("объектов (Raw)") if mode == "raw" else tr("дампов")
        title = tr("Экспорт {kind} «{script}»", kind=kind_word, script=script_name)
        task_id = win.task_queue_manager.enqueue(
            TaskKind.EXPORT, title, self._make_bulk_export_fn(items, export_dir, mode, kind_word)
        )
        self._task_followups[task_id] = {
            "title": title, "folder": export_dir, "on_success": lambda: self._maybe_open_folder(export_dir),
        }
        win.log(tr("Добавлено в очередь: экспорт {count} {kind} «{script}». Открыть очередь задач можно в "
                   "строке состояния.", count=len(items), kind=kind_word, script=script_name), LogLevel.WARNING)

    def export_type_objects_as(self, type_name: str, mode: str):
        """"Экспортировать все объекты типа X как →" — every object of this type
        currently indexed (win.raw_data_list), deliberately unfiltered by the
        table's current filter/selection: the whole point is a quick export
        without the Filters-dialog-then-select-all workflow."""
        win = self.main_window
        items = [item for item in win.raw_data_list if item.get("type") == type_name]
        if not items:
            win.log(tr("Не найдено объектов типа «{type}» для экспорта.", type=type_name), LogLevel.WARNING)
            return
        kind_word = {
            "converted": tr("объектов"), "json_dump": tr("дампов"),
            "raw": tr("объектов (Raw)"), "content_raw": tr("объектов (Content Raw)"),
        }.get(mode, tr("объектов"))
        self._run_bulk_export(items, mode, kind_word, tr("Экспорт всех объектов типа «{type}»", type=type_name))

    def export_selected_objects(self, items: list):
        """Multi-row-selection counterpart to export_selected_object() —
        type-appropriate export (core.object_preview.export_object) for every
        selected row, one queued task with real progress instead of N separate
        ones (matching dump_by_script_type()'s existing shape)."""
        self._run_bulk_export(items, "converted", tr("объектов"), tr("Экспорт объектов"))

    def dump_multiple_objects_json(self, items: list):
        """Multi-row-selection counterpart to dump_single_object() — JSON-dumps
        every selected row into one chosen folder."""
        self._run_bulk_export(items, "json_dump", tr("дампов"), tr("Экспорт дампов"))

    def export_selected_objects_raw(self, items: list):
        """Multi-row-selection counterpart to export_raw_single() — the object's
        own serialized bytes for every selected row."""
        self._run_bulk_export(items, "raw", tr("объектов (Raw)"), tr("Экспорт объектов (Raw)"))
