"""«Подготовить скрипты IL2CPP»: runs the bundled Il2CppDumper for the loaded IL2CPP game (core/il2cpp_dummy.py) and
switches the loaded game to the result at once — no reload (core.loader.build_prepared_generator in the worker, then
install_prepared_generator on the GUI thread, then `on_applied` so the window re-reads what it shows).

Kept bare on purpose (user feedback: the first version was cluttered with explanations; then an entirely empty window
was not enough either): a console pane that shows the dumper's own output live once it starts — before that it holds
a one-sentence grey placeholder (what this does) — one status line and the buttons. The status line states the
outcome, not a bare fact (a plain "already prepared" left the user asking what it meant): «Для этой игры всё готово.»
(prepared and used by this load: only «Закрыть»), «Уже подготовлено.» + «Применить» (prepared, not used by this load
yet), the own-Managed line (prepared files are not used then), or nothing; at the end: done / the plain error /
cancelled. The start button says «Запустить» (the user's caption; «Подготовить заново» confused them) and is not
offered when the result already exists (the same files would make the same DLLs).

Closing the dialog while it works cancels a running preparation and waits for the worker, so the dialog is never
destroyed under a running thread (it is opened through exec_and_dispose)."""

from core.i18n import N_, tr
import logging

from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout,
)

from core import il2cpp_dummy
from core.loader import build_prepared_generator, install_prepared_generator
from gui_workers import BackgroundWorker
from helpers import mono_font

logger = logging.getLogger("ustudio.il2cpp")

# Shown in the empty console (placeholder): gone as soon as the tool's own output starts.
_INTRO = N_("UStudio извлечёт описание скриптов из файлов игры, чтобы объекты MonoBehaviour читались полностью. Чтобы начать операцию, нажмите кнопку \"Сгенерировать DLL\".")
# Opening states (only one applies): what the user gets, not just a fact. Running again on the same files would
# make the same DLLs, so in the two "prepared" states there is no «Запустить» button.
_READY = N_("Для этой игры всё готово.")                                        # prepared AND used by this load
_PREPARED_NOT_USED = N_("Уже подготовлено.")                                     # prepared, this load does not use them yet
_OWN_MANAGED = N_("В игре есть своя папка Managed — скрипты будут читаться с помощью неё.")  # prepared files unused anyway


class Il2CppPrepareDialog(QDialog):
    def __init__(self, inputs: "il2cpp_dummy.Il2CppInputs", env=None, has_own_managed: bool = False,
                 in_use: bool = False, on_applied=None, parent=None):
        """env: the loaded game, switched to the prepared DLLs when done (None: only prepare them).
        in_use: the current load already reads scripts with them (env.il2cpp_dummy_dir).
        on_applied: called on the GUI thread after the switch (the window re-reads its preview)."""
        super().__init__(parent)
        self.setWindowTitle("Il2CppDumper")
        self.resize(620, 360)
        self._inputs = inputs
        self._env = env
        self._on_applied = on_applied
        self._worker = None
        self._cancel = False

        layout = QVBoxLayout(self)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(mono_font())
        self.console.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.console.setPlaceholderText(tr(_INTRO))
        layout.addWidget(self.console, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)                     # busy: the dumper reports no measurable progress
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(6)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.btn_start = QPushButton(tr("Сгенерировать DLL"))
        self.btn_start.setDefault(True)
        self.btn_start.clicked.connect(lambda: self._run(generate=True))
        self.btn_apply = QPushButton(tr("Применить"))
        self.btn_apply.clicked.connect(lambda: self._run(generate=False))
        self.btn_apply.hide()
        self.btn_close = QPushButton(tr("Закрыть"))
        self.btn_close.clicked.connect(self.reject)
        for b in (self.btn_start, self.btn_apply, self.btn_close):
            buttons.addWidget(b)
        layout.addLayout(buttons)

        prepared = il2cpp_dummy.cached_dummy_dir(inputs) is not None
        if has_own_managed:
            self._set_status(tr(_OWN_MANAGED))
        elif prepared and in_use:
            self._set_status(tr(_READY))
            self.btn_start.hide()
            self.btn_close.setDefault(True)
        elif prepared:
            self._set_status(tr(_PREPARED_NOT_USED))
            self.btn_start.hide()
            self.btn_apply.setVisible(self._can_apply())
            self.btn_apply.setDefault(True)
        else:
            self._set_status("")

    def _can_apply(self) -> bool:
        return self._env is not None and bool(getattr(self._env, "typetree_unity_version", ""))

    # --- states ---

    def _run(self, generate: bool):
        self._cancel = False
        if generate:
            self.console.clear()
        self._set_status("")
        self.btn_start.hide()
        self.btn_apply.hide()
        self.btn_close.setText(tr("Отмена"))
        self.progress.show()

        inputs, can_apply = self._inputs, self._can_apply()
        version = getattr(self._env, "typetree_unity_version", "")

        def work(report_progress):
            """-> (DummyDll folder, a reader over it or None) / None when cancelled."""
            try:
                if generate:
                    dummy_dir = il2cpp_dummy.generate(inputs, should_cancel=lambda: self._cancel,
                                                      on_line=lambda line: report_progress(line, None, None))
                else:
                    dummy_dir = il2cpp_dummy.cached_dummy_dir(inputs)
            except il2cpp_dummy.DumperCancelled:
                return None
            except il2cpp_dummy.DumperError as e:
                if e.details:
                    logger.warning("Il2CppDumper: %s\n%s", e, e.details)   # i18n: keep (the tool's own output)
                raise
            # the slow part of switching the loaded game (~2.5 s the first time) stays off the GUI thread
            generator = build_prepared_generator(version, dummy_dir) if can_apply else None
            return dummy_dir, generator

        self._worker = BackgroundWorker(work, parent=self)
        self._worker.progress_signal.connect(lambda line, _a, _b: self.console.appendPlainText(line))
        self._worker.succeeded_signal.connect(self._on_done)
        self._worker.failed_signal.connect(self._on_failed)
        self._worker.start()

    def _set_status(self, text: str):
        self.status_label.setText(text)
        self.status_label.setVisible(bool(text))

    def _end_run(self):
        self.progress.hide()
        self.btn_close.setText(tr("Закрыть"))

    def _on_done(self, result):
        self._end_run()
        if result is None:                               # cancelled
            self._set_status(tr("Отменено."))
            self.btn_start.show()
            return
        dummy_dir, generator = result
        count = len(list(dummy_dir.glob("*.dll")))
        # verb and noun agree with the number: «Сгенерирована 1 фиктивная библиотека», «…ы 2 …ые …и», «…о 5 …ых …»
        
        if generator is None:
            self._set_status(tr("Готово"))
            return
        install_prepared_generator(self._env, generator, dummy_dir)
        self._set_status(tr("Готово. Это окно можно закрыть."))
        self.btn_close.setDefault(True)
        if self._on_applied is not None:
            self._on_applied()

    def _on_failed(self, message):
        self._end_run()
        self._set_status(message)
        self.btn_start.show()

    def reject(self):
        """Esc / Отмена / Закрыть / the window's close button: a running preparation is cancelled and waited for."""
        if self._worker is not None and self._worker.isRunning():
            self._cancel = True
            self._worker.wait(15000)
        super().reject()
