"""TaskQueuePanel — the popup opened by clicking gui_widgets.TaskQueueStatusWidget in
the main window's status bar. Two tabs: "Задачи" lists every active/pending export/
import task (task_queue.TaskQueueManager already drops finished/failed/cancelled ones
from the active list — see its docstring), each with a progress bar and its own Cancel
button, plus a header summarizing the currently running task (queue/done/succeeded/
failed counts, elapsed time) and one "Отменить всё" button for the whole queue.
"Журнал" shows per-item notes (a skipped-but-not-really-an-error item, e.g. an empty
texture; a genuine per-item failure within an otherwise-successful bulk operation) for
the running task and the last few finished ones (TaskQueueManager.history()) — without
cluttering the main app log with them. Non-modal: exporting/importing something else
while this is open should still work normally, it's just a viewer/controller for the
same queue the status bar summarizes.

Deliberately NOT a live per-file log of every individual exported file (the way e.g.
FModel's export session window does it) — considered and turned down: this app's tasks
can span hundreds of thousands of objects, and per-item GUI updates at that scale are
exactly the class of bug this project has hit and fixed more than once already (see
gui_workers.ProgressThrottle's docstring, and the disk-backed-rebuild progress-flood
fix in CLAUDE.md) — a live per-file list would need a virtualized model and throttled/
batched streaming, a genuinely bigger and riskier piece of work than what's here. The
"Журнал" tab stays safe at that scale the same way the rest of this file does: entries
are batched at the same throttled cadence as progress reporting (never one update per
item — see task_queue.TaskFn's docstring), hard-capped per task
(task_queue._MAX_LOG_ENTRIES), and only actually re-rendered while the tab itself is
visible."""

from core.i18n import tr
import html
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTabWidget, QTextEdit,
    QVBoxLayout, QWidget,
)

import theme
from task_queue import LogNote, TaskKind, TaskStatus

# Names listed per merged group in the Журнал tab (the rest collapse into "… и ещё N").
_MAX_LOG_NAMES_SHOWN = 8

_SUCCEEDED_COLOR = "#43a047"
_FAILED_COLOR = "#e53935"


def _format_duration(seconds: float) -> str:
    """M:SS, or H:MM:SS past an hour — the elapsed time."""
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class _StatCell(QWidget):
    """One "value \\n caption" cell in the header, e.g. a big "33 310" over a
    small gray "в очереди" — the same layout FModel's own export session
    window uses for its header counters."""

    def __init__(self, caption: str, color: str = None, align_right: bool = False, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(0)

        self.value_label = QLabel("0")
        value_font = self.value_label.font()
        value_font.setPointSize(value_font.pointSize() + 4)
        value_font.setBold(True)
        self.value_label.setFont(value_font)
        if color:
            self.value_label.setStyleSheet(f"color: {color};")

        caption_label = QLabel(caption)
        caption_label.setStyleSheet("color: gray;")
        caption_font = caption_label.font()
        caption_font.setPointSize(max(7, caption_font.pointSize() - 1))
        caption_label.setFont(caption_font)

        if align_right:
            self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            caption_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        layout.addWidget(self.value_label)
        layout.addWidget(caption_label)

    def set_value(self, text: str) -> None:
        self.value_label.setText(text)


class _QueueHeader(QWidget):
    """Summarizes whichever task is currently RUNNING (at most one, ever — see
    task_queue.py's module docstring) — total/succeeded/failed counts and an
    the time elapsed since it started. Real reported requests: dropped the
    "готово" (done) count — redundant with each row's own N/N progress
    fraction — and showed elapsed time instead of an ETA extrapolated from
    the current rate (which jumped around and was often a poor guess). Idle (nothing running — the
    queue is empty, or every remaining task is still PENDING) just shows
    zeros/placeholders rather than stale numbers from whatever ran last,
    since that task is already gone from the queue by then (see
    TaskQueueManager's docstring on why finished tasks aren't kept
    around)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 6, 4, 6)

        self.total_cell = _StatCell(tr("всего"))
        self.succeeded_cell = _StatCell(tr("успешно"), color=_SUCCEEDED_COLOR)
        self.failed_cell = _StatCell(tr("ошибок"), color=_FAILED_COLOR)
        layout.addWidget(self.total_cell)
        layout.addWidget(self.succeeded_cell)
        layout.addWidget(self.failed_cell)
        layout.addStretch(1)
        self.elapsed_cell = _StatCell(tr("прошло"), align_right=True)
        layout.addWidget(self.elapsed_cell)

    def update_from(self, task) -> None:
        if task is None:
            self.total_cell.set_value("—")
            self.succeeded_cell.set_value("—")
            self.failed_cell.set_value("—")
            self.elapsed_cell.set_value("--:--")
            return

        self.total_cell.set_value(f"{task.progress_total:,}".replace(",", " "))
        self.succeeded_cell.set_value(f"{task.succeeded_count:,}".replace(",", " "))
        self.failed_cell.set_value(f"{task.failed_count:,}".replace(",", " "))

        elapsed = time.monotonic() - task.started_at if task.started_at is not None else 0.0
        self.elapsed_cell.set_value(_format_duration(elapsed))


class _SectionLabel(QLabel):
    """"Выполняется" / "В очереди (N)" — a small caption above each grouped
    section of rows. update_count() also drives its own visibility: a section
    with nothing in it disappears entirely rather than showing an empty
    heading over blank space. show_count=False (used for "Выполняется", which
    is always exactly 0 or 1 — see task_queue.py's module docstring — so the
    count is redundant there) leaves the label as plain text regardless of
    how many rows are actually in the section."""

    def __init__(self, text: str, show_count: bool = True, parent=None):
        super().__init__(text, parent)
        self._base_text = text
        self._show_count = show_count
        font = self.font()
        font.setBold(True)
        self.setFont(font)
        self.setStyleSheet("color: gray;")
        self.setContentsMargins(4, 6, 4, 2)
        self.hide()

    def update_count(self, count: int) -> None:
        if self._show_count and count:
            self.setText(f"{self._base_text} ({count})")
        else:
            self.setText(self._base_text)
        self.setVisible(count > 0)


class _TaskRow(QWidget):
    def __init__(self, task, manager, parent=None):
        super().__init__(parent)
        self.task_id = task.task_id
        self._manager = manager

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        # Real reported request: the leftover-of-a-single-string
        # "[Экспорт] title" made the type hard to scan at a glance across
        # several rows — split into its own fixed-width column showing just
        # the type (plain "Экспорт"/"Импорт", no brackets). A separate title
        # column was tried right after and then explicitly asked to be
        # dropped again — the task's own title is folded into status_label's
        # own text instead (see update_from()).
        kind_text = tr("Экспорт") if task.kind == TaskKind.EXPORT else tr("Импорт")
        self.kind_label = QLabel(kind_text)
        self.kind_label.setMinimumWidth(70)
        layout.addWidget(self.kind_label)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label, 1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(140)
        self.progress_bar.setRange(0, 0)   # indeterminate until the task reports real totals
        layout.addWidget(self.progress_bar)

        self.cancel_btn = QPushButton(tr("Отмена"))
        self.cancel_btn.clicked.connect(lambda: manager.cancel_task(self.task_id))
        layout.addWidget(self.cancel_btn)

        self.update_from(task)

    def update_from(self, task) -> None:
        # Real reported request: dropped the separately-worded phase text
        # (e.g. "Экспорт объектов... (500/137609)") — it just repeated what
        # kind_label already says plus the title a second time. Title + a
        # plain progress fraction says the same thing without the repetition.
        title = task.title or ""
        if task.status == TaskStatus.PENDING:
            self.status_label.setText(tr("{title} — в очереди", title=title) if title else tr("в очереди"))
        elif task.status == TaskStatus.RUNNING:
            progress = f" {task.progress_current}/{task.progress_total}" if task.progress_total else ""
            self.status_label.setText(f"{title}...{progress}" if title else tr("выполняется...{progress}", progress=progress))
        if task.progress_total:
            # See gui_workers.BackgroundWorker's docstring for why these are plain
            # Python ints rather than something a 32-bit QProgressBar could overflow
            # on for a byte-count-scale task — normalize onto a fixed 0..10000 range
            # the same way CabBrowserDialog._on_rebuild_progress already does.
            fraction = min(max(task.progress_current / task.progress_total, 0.0), 1.0)
            self.progress_bar.setRange(0, 10000)
            self.progress_bar.setValue(int(fraction * 10000))
        else:
            self.progress_bar.setRange(0, 0)


class TaskQueuePanel(QDialog):
    # How often the header's elapsed time re-renders on its own, independent of any
    # actual progress event — without this it would visibly freeze between
    # throttled progress updates (ProgressThrottle reports at most once per
    # ~150ms per task, but a single very large item can go quiet for much
    # longer than that) even though real time keeps passing.
    _HEADER_TICK_MS = 500

    _TASKS_TAB, _LOG_TAB = range(2)

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Очередь задач"))
        # Wide enough that the "Журнал" tab's placeholder text (one long
        # sentence, Consolas 9pt) renders as a single line instead of
        # wrapping — real reported complaint, the original 560px width
        # clipped/wrapped it.
        self.resize(560, 420)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self._manager = manager
        self._rows: dict[int, _TaskRow] = {}
        # Which of the two section layouts below each row currently lives in —
        # needed to reparent a row from "В очереди" to "Выполняется" the
        # moment the worker actually picks it up, without tearing the whole
        # list down and rebuilding it from scratch every refresh.
        self._row_section: dict[int, QVBoxLayout] = {}

        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        tasks_tab = QWidget()
        tasks_layout = QVBoxLayout(tasks_tab)

        self.header = _QueueHeader()
        tasks_layout.addWidget(self.header)

        self.empty_label = QLabel(tr("Нет активных или ожидающих задач."))
        self.empty_label.setStyleSheet("color: gray;")
        tasks_layout.addWidget(self.empty_label)

        # Real reported request: pending tasks read as one undifferentiated
        # list alongside whatever's actually running — grouped into its own
        # labeled "В очереди" section instead, separate from the (at most
        # one, ever — see task_queue.py) running task's own row.
        self.running_label = _SectionLabel(tr("Выполняется"), show_count=False)
        tasks_layout.addWidget(self.running_label)
        self.running_layout = QVBoxLayout()
        self.running_layout.setSpacing(2)
        tasks_layout.addLayout(self.running_layout)

        self.queue_label = _SectionLabel(tr("В очереди"))
        tasks_layout.addWidget(self.queue_label)
        self.queue_layout = QVBoxLayout()
        self.queue_layout.setSpacing(2)
        tasks_layout.addLayout(self.queue_layout)

        tasks_layout.addStretch()
        self.tabs.addTab(tasks_tab, tr("Задачи"))

        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        self._last_log_html = ""
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        # Real reported bug: QTextEdit's placeholder rendering doesn't treat an
        # embedded "\n" as a real line break the way normal content does — it
        # only ever showed the first line, the rest silently invisible. One
        # continuous sentence with no hard breaks lets Qt's own word-wrap
        # (the widget's normal WidgetWidth wrap mode, same as real content)
        # flow it across as many visual lines as the width needs instead.
        self.log_view.setPlaceholderText(
            tr("Здесь появятся объекты, которые были пропущены или завершились ошибкой")
        )
        log_layout.addWidget(self.log_view)
        self.tabs.addTab(log_tab, tr("Журнал"))

        button_row = QHBoxLayout()
        self.cancel_all_btn = QPushButton(tr("Отменить всё"))
        self.cancel_all_btn.clicked.connect(manager.cancel_all)
        close_btn = QPushButton(tr("Закрыть"))
        close_btn.clicked.connect(self.close)
        button_row.addWidget(self.cancel_all_btn)
        button_row.addStretch()
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        manager.task_added.connect(lambda _tid: self._refresh())
        manager.task_started.connect(lambda _tid: self._refresh())
        manager.task_progress.connect(self._on_task_progress)
        manager.queue_changed.connect(self._refresh)
        manager.history_changed.connect(self._on_history_changed)
        # Only re-renders the log tab's (potentially large, though bounded —
        # see the module docstring) text while it's the one actually being
        # looked at — refreshing it on every throttled progress tick
        # regardless would be wasted work the rest of the time.
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Keeps the header's elapsed time ticking even between throttled
        # progress events — see _HEADER_TICK_MS's own comment. Only while the
        # panel is actually visible: no point re-rendering a hidden dialog.
        self._header_timer = QTimer(self)
        self._header_timer.setInterval(self._HEADER_TICK_MS)
        self._header_timer.timeout.connect(lambda: self.header.update_from(self._manager.running_task()))

        self._refresh()
        self._refresh_log()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._header_timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._header_timer.stop()

    def _on_task_progress(self, *_args) -> None:
        self._refresh()
        if self.tabs.currentIndex() == self._LOG_TAB:
            self._refresh_log()

    def _on_tab_changed(self, index: int) -> None:
        if index == self._LOG_TAB:
            self._refresh_log()

    def _on_history_changed(self) -> None:
        if self.tabs.currentIndex() == self._LOG_TAB:
            self._refresh_log()

    @staticmethod
    def _render_task_section(colors, header: str, state: str, entries: list, truncated: bool) -> str:
        """One task's block: a bold title with a muted state, then its notes.
        LogNotes with the same (kind, reason) are merged across the WHOLE task
        (the producer flushes per progress window, so the same reason can
        arrive many times) into one group — a coloured heading with the total
        count, then the first few names as a list. Plain-str entries are shown
        as-is, in order, before the groups."""
        muted = colors.disabled_text
        plain = []
        groups: dict = {}
        for e in entries:
            if isinstance(e, LogNote):
                g = groups.setdefault((e.kind, e.reason), [0, []])
                g[0] += e.count
                for n in e.names:
                    if len(g[1]) < _MAX_LOG_NAMES_SHOWN and n not in g[1]:
                        g[1].append(n)
            else:
                plain.append(str(e))

        out = [
            f'<div style="margin-top:14px; margin-bottom:6px;">'
            f'<span style="font-size:11pt; font-weight:600;">{html.escape(header)}</span>'
            f'<span style="color:{muted};"> &nbsp;·&nbsp; {html.escape(state)}</span></div>'
        ]
        for line in plain:
            out.append(f'<div style="margin-left:10px;">{html.escape(line)}</div>')
        for (kind, reason), (count, names) in groups.items():
            is_error = kind == "error"
            color = colors.log_error if is_error else colors.log_warning
            label = tr("Ошибки") if is_error else tr("Пропущено")
            out.append(
                f'<div style="margin-top:8px; margin-left:10px;">'
                f'<span style="color:{color}; font-weight:600;">{label}: {count}</span>'
                f'<span style="color:{muted};"> &nbsp;—&nbsp; {html.escape(reason)}</span></div>'
            )
            for n in names:
                out.append(f'<div style="margin-left:28px;">&bull; {html.escape(n)}</div>')
            if count > len(names):
                out.append(
                    tr("<div style=\"margin-left:28px; color:{muted};\">… и ещё {value}</div>", muted=muted, value=count - len(names))
                )
        if truncated:
            out.append(tr("<div style=\"margin-left:10px; color:{muted};\">… показаны не все записи</div>", muted=muted))
        return "".join(out)

    def _refresh_log(self) -> None:
        """Renders every log_entries list currently worth showing — the
        running/pending tasks' own (see task_queue.TaskFn's docstring on how
        those get batched in) plus the last few finished tasks'
        (TaskQueueManager.history()) — into one plain-text view. Only actually
        does this while the "Журнал" tab is the visible one (see
        _on_task_progress/_on_tab_changed) — everything it reads is already
        bounded (task_queue._MAX_LOG_ENTRIES per task, TaskQueueManager.
        _MAX_HISTORY tasks of history), so a full rebuild here is cheap
        relative to that skip, not because the skip is masking something
        expensive."""
        colors = theme.get_colors(theme.load_saved_theme_name())
        sections = []
        for task in self._manager.list_tasks():
            if not task.log_entries:
                continue
            kind_text = tr("Экспорт") if task.kind == TaskKind.EXPORT else tr("Импорт")
            state = tr("выполняется") if task.status == TaskStatus.RUNNING else tr("в очереди")
            # Real reported issue: several task titles are already self-
            # describing ("Экспорт объектов", "Импорт патчей из папки") —
            # prepending kind_text unconditionally produced a tautology like
            # "Экспорт: Экспорт объектов". Others are just the object's own
            # name ("MyTexture") and genuinely need the prefix — so only add
            # it when the title doesn't already start with the same word.
            header = task.title if task.title.startswith(kind_text) else f"{kind_text}: {task.title}"
            sections.append(self._render_task_section(colors, header, state, task.log_entries, task.log_truncated))

        status_word = {
            TaskStatus.DONE: tr("завершено"),
            TaskStatus.FAILED: tr("ошибка"),
            TaskStatus.CANCELLED: tr("отменено"),
        }
        for entry in self._manager.history():  # newest first
            if not entry.log_entries:
                continue
            kind_text = tr("Экспорт") if entry.kind == TaskKind.EXPORT else tr("Импорт")
            header = entry.title if entry.title.startswith(kind_text) else f"{kind_text}: {entry.title}"
            sections.append(self._render_task_section(
                colors, header, status_word.get(entry.status, ""), entry.log_entries, entry.log_truncated))

        html_text = "".join(sections)
        if html_text == self._last_log_html:
            return  # nothing actually changed — don't disturb scroll position/selection for no reason
        self._last_log_html = html_text
        bar = self.log_view.verticalScrollBar()
        was_at_bottom = bar.value() >= bar.maximum() - 4
        self.log_view.setHtml(html_text)
        if was_at_bottom:
            bar.setValue(bar.maximum())

    def _refresh(self) -> None:
        tasks = self._manager.list_tasks()
        current_ids = {t.task_id for t in tasks}

        for task_id in list(self._rows.keys()):
            if task_id not in current_ids:
                row = self._rows.pop(task_id)
                self._row_section.pop(task_id, None)
                row.setParent(None)
                row.deleteLater()

        running_tasks = [t for t in tasks if t.status == TaskStatus.RUNNING]
        pending_tasks = [t for t in tasks if t.status == TaskStatus.PENDING]
        self._sync_section(running_tasks, self.running_layout)
        self._sync_section(pending_tasks, self.queue_layout)

        self.running_label.update_count(len(running_tasks))
        self.queue_label.update_count(len(pending_tasks))

        self.header.update_from(self._manager.running_task())
        self.empty_label.setVisible(not tasks)
        self.cancel_all_btn.setEnabled(bool(tasks))

    def _sync_section(self, section_tasks: list, section_layout: QVBoxLayout) -> None:
        """Adds/updates each of section_tasks' rows in section_layout,
        reparenting a row out of whichever OTHER section it used to be in if
        this is the first refresh since it moved (currently only one
        transition ever happens: a task's row starts in queue_layout while
        PENDING and moves to running_layout the moment the worker picks it
        up)."""
        for task in section_tasks:
            row = self._rows.get(task.task_id)
            if row is None:
                row = _TaskRow(task, self._manager, self)
                self._rows[task.task_id] = row
                self._row_section[task.task_id] = section_layout
                section_layout.addWidget(row)
                continue
            if self._row_section.get(task.task_id) is not section_layout:
                old_layout = self._row_section.get(task.task_id)
                if old_layout is not None:
                    old_layout.removeWidget(row)
                section_layout.addWidget(row)
                self._row_section[task.task_id] = section_layout
            row.update_from(task)
