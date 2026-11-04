"""One shared dialog for every converted-import type (Texture/Audio; Video
joins later — see ROADMAP.md), rather than a separate dialog per type, per
explicit preference ("the latter for convenience"). Reached ONLY via a
dedicated "...(с настройками)..." menu action — object_actions.py only offers
that action when at least one selected object's type is in
core.object_preview.CONVERTED_IMPORT_SUPPORTED_TYPES, so this dialog never
needs to handle "nothing relevant to show" itself. The plain "Импортировать из
файла..."/"Импортировать из папки..." actions never open this at all; they
always run silently with CONFIG's saved defaults. No "ask before import"/
"don't show again" toggle exists anymore — two separate actions replaced that
one gated switch (see config.py's own comment on texture_import_format_mode
for why).

Only the section relevant to the given type is built — a Texture2D/
Texture2DArray selection gets the "Текстура" box, an AudioClip selection gets
"Аудио". Extending this for Video means adding a new branch here, not a new
dialog class.

Takes exactly one type name. This dialog briefly (one session) accepted a SET
of type names and built one section per distinct type present, side-by-side,
to cover a bulk "...с настройками" selection spanning several different
converted-import types at once (a folder with both Texture and Audio
patches, say) — but that capability went unreachable the moment
object_actions.py's own bulk context menu was restricted to only offer
"...с настройками" for a selection that's already a single, homogeneous type
(a separate, deliberate fix — showing a multi-section configuration dialog
for a table selection the user never intended to configure together was
itself the actual bug). Removed rather than left as unused code once nothing
could reach it anymore — a bulk selection now always resolves to exactly one
type before this dialog is ever constructed, same as the single-object entry
points always have.
"""

from core.i18n import tr
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSizePolicy, QSlider, QVBoxLayout,
)

from core import video_transcode
from core.object_preview import peek_videoclip_ext, texture_format_platform_warning
from .app_settings_dialog import (
    TEXTURE_FORMAT_MODE_OPTIONS, _grow_to_fit, _make_help_icon,
    build_audio_quality_slider, build_texture_manual_format_combo,
)

_TEXTURE_TYPES = {"Texture2D", "Texture2DArray"}


class ConvertedImportSettingsDialog(QDialog):
    def __init__(self, parent, type_name: str, current_values: dict, platform=None, version=None,
                 source_file_path=None, obj=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Параметры импорта"))
        self.setModal(True)
        self._platform = platform
        # BC7 version gating — BC7 has no TextureFormat enum value before
        # Unity 5, so offering it as a manual-format choice for an older
        # object would let a user pick a format their own engine build can't
        # actually decode. Only gates the MANUAL picker: match_original never
        # needs this — it only ever reuses whatever format already legitimately
        # exists on the object, which by construction can't be a format that
        # object's own engine version doesn't support in the first place.
        exclude_formats = {"BC7"} if version is not None and getattr(version, "major", 999) < 5 else set()

        outer = QVBoxLayout(self)

        self.combo_format_mode: Optional[QComboBox] = None
        self.combo_manual_format: Optional[QComboBox] = None
        self.cb_mipmaps: Optional[QCheckBox] = None
        self.slider_audio_quality: Optional[QSlider] = None
        self._format_warning_label: Optional[QLabel] = None
        self._texture_box: Optional[QGroupBox] = None
        self.cb_video_transcode: Optional[QCheckBox] = None
        self.combo_video_target: Optional[QComboBox] = None
        self.label_video_target_resolved: Optional[QLabel] = None
        self.slider_video_quality: Optional[QSlider] = None
        self.edit_video_output_path: Optional[QLineEdit] = None
        self._video_transcode_options_widget = None
        self._video_output_path_is_suggested = False
        self._source_file_path = Path(source_file_path) if source_file_path else None

        # "Same as original" support (VideoClip only) — obj is the single
        # object actually being imported into, when known (never given for a
        # bulk selection spanning several different clips, which can't share
        # one "original format" answer). Resolved ONCE here, at construction,
        # so both the output-path extension suggestion below and accept()'s
        # own fallback prompt agree on the same answer for the same object.
        self._obj = obj
        self._resolved_original_target: Optional[str] = None
        if obj is not None:
            self._resolved_original_target = video_transcode.target_for_container_ext(peek_videoclip_ext(obj))
        # Set by accept() itself if the user agrees to a fallback format for
        # THIS import only, when "original" couldn't be resolved above — kept
        # separate from the combo's own persisted selection (which stays
        # "original" in CONFIG regardless, so the NEXT clip — which might
        # resolve just fine — still gets offered "original" first).
        self._original_fallback_target: Optional[str] = None

        if type_name in _TEXTURE_TYPES:
            # Texture2DArray shares this box's quality/mipmap controls but NOT
            # the format picker — import_texture_array_slices() always
            # re-encodes into the array's own existing format (see
            # Texture2DArray.set_images()'s docstring for why a manual target
            # format isn't offered: the GraphicsFormat<->TextureFormat mapping
            # is many-to-one and irreversible without guessing).
            show_format_picker = type_name == "Texture2D"
            texture_box = self._texture_box = QGroupBox(tr("Текстура"))
            texture_layout = QVBoxLayout(texture_box)

            if show_format_picker:
                texture_layout.addWidget(QLabel(tr("Формат:")))
                self.combo_format_mode = QComboBox()
                self.combo_format_mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                self.combo_format_mode.setMinimumContentsLength(1)
                self.combo_format_mode.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                for value, label in TEXTURE_FORMAT_MODE_OPTIONS:
                    self.combo_format_mode.addItem(tr(label), value)
                idx = self.combo_format_mode.findData(current_values.get("texture_import_format_mode", "match_original"))
                self.combo_format_mode.setCurrentIndex(idx if idx >= 0 else 0)
                self.combo_format_mode.currentIndexChanged.connect(self._on_format_choice_changed)
                texture_layout.addWidget(self.combo_format_mode)

                self.combo_manual_format = build_texture_manual_format_combo(exclude_formats)
                idx = self.combo_manual_format.findData(current_values.get("texture_import_manual_format", "BC7"))
                self.combo_manual_format.setCurrentIndex(idx if idx >= 0 else 0)
                self.combo_manual_format.currentIndexChanged.connect(self._on_format_choice_changed)
                texture_layout.addWidget(self.combo_manual_format)

                if exclude_formats:
                    # Real consequence worth spelling out, not just silently
                    # substituting: if the user's saved manual-format default
                    # is BC7 (config.py's own default value), it's not in
                    # this list at all right now — the combo above already
                    # fell back to its first entry instead — and clicking OK
                    # persists WHATEVER this combo currently shows as the new
                    # saved default, which would silently replace a BC7
                    # preference with something else if the user doesn't
                    # notice and just clicks through.
                    bc7_gate_note = QLabel(
                        tr("BC7 недоступен для объектов из версий Unity старше 5.0 — он отсутствует в списке для этого "
                           "объекта. Если вы нажмёте OK, выбранный здесь формат будет сохранён как новый формат по "
                           "умолчанию.")
                    )
                    bc7_gate_note.setWordWrap(True)
                    bc7_gate_note.setStyleSheet("color: #b8860b;")
                    texture_layout.addWidget(bc7_gate_note)

                # Soft, informational only — never blocks OK. See
                # texture_format_platform_warning()'s own docstring for exactly
                # which mismatches this actually fires on (deliberately narrow).
                self._format_warning_label = QLabel()
                self._format_warning_label.setWordWrap(True)
                self._format_warning_label.setStyleSheet("color: #b8860b;")
                texture_layout.addWidget(self._format_warning_label)
            else:
                note = QLabel(
                    tr("Формат не выбирается — срезы всегда перекодируются в формат, уже используемый этим "
                       "Texture2DArray.")
                )
                note.setWordWrap(True)
                texture_layout.addWidget(note)

            self.cb_mipmaps = QCheckBox(tr("Генерировать мип-уровни"))
            self.cb_mipmaps.setChecked(bool(current_values.get("texture_import_mipmaps", False)))
            texture_layout.addWidget(self.cb_mipmaps)
            # Grow-only resizing (_grow_to_fit, see _update_manual_format_visibility
            # below) can leave this box taller than its current content needs — real
            # reported bug without this: with no stretch anywhere in this layout, Qt's
            # own default extra-space distribution left an ugly gap in the MIDDLE of
            # the box (right where combo_manual_format/the warning label used to sit)
            # instead of cleanly at the bottom. An explicit trailing stretch pins any
            # leftover space to the bottom, deterministically, regardless of Qt's
            # otherwise-unpredictable default.
            texture_layout.addStretch(1)
            outer.addWidget(texture_box)

            # Real bug fixed while adding the Audio section: this used to be
            # called unconditionally whenever the type was in
            # CONVERTED_IMPORT_SUPPORTED_TYPES — which already included
            # Texture2DArray, whose combo_format_mode is None (no format
            # picker for that type) — crashing every "Импортировать срезы из
            # папки (с настройками)..." click with AttributeError. Only
            # meaningful when the format picker actually exists.
            if show_format_picker:
                self._on_format_choice_changed()

        elif type_name == "AudioClip":
            audio_box = QGroupBox(tr("Аудио"))
            audio_layout = QVBoxLayout(audio_box)
            audio_format_note = QLabel(
                tr("Формат сжатия не выбирается — всегда используется формат, уже объявленный этим AudioClip "
                   "(поддерживаются PCM и Vorbis).")
            )
            audio_format_note.setWordWrap(True)
            audio_layout.addWidget(audio_format_note)
            audio_quality_label_row = QHBoxLayout()
            audio_quality_label_row.addWidget(QLabel(tr("Качество:")))
            audio_quality_widget, self.slider_audio_quality, audio_quality_help = build_audio_quality_slider(
                int(current_values.get("audio_import_quality", 0)), help_icon=True
            )
            audio_quality_label_row.addWidget(audio_quality_help)
            audio_quality_label_row.addStretch(1)
            audio_layout.addLayout(audio_quality_label_row)
            audio_layout.addWidget(audio_quality_widget)
            audio_layout.addStretch(1)
            outer.addWidget(audio_box)

        elif type_name == "VideoClip":
            video_box = QGroupBox(tr("Видео"))
            video_layout = QVBoxLayout(video_box)

            # Off by default and never persisted anywhere (see config.py —
            # there's deliberately no CONFIG.video_transcode_* default at
            # all): transcoding is real, potentially slow encoding work, and
            # this project's own established preference is that nothing this
            # heavy should ever run except as an explicit, one-off choice —
            # the plain silent "Импортировать из файла..." action never sees
            # this checkbox at all and always just packages the file as-is,
            # exactly as before this feature existed.
            self.cb_video_transcode = QCheckBox(tr("Транскодировать видео"))
            self.cb_video_transcode.setChecked(False)
            self.cb_video_transcode.toggled.connect(self._on_video_transcode_toggled)
            video_layout.addWidget(self.cb_video_transcode)

            options_widget = self._video_transcode_options_widget = QGroupBox()
            options_widget.setFlat(True)
            options_layout = QVBoxLayout(options_widget)
            options_layout.setContentsMargins(0, 0, 0, 0)

            options_layout.addWidget(QLabel(tr("Формат:")))
            self.combo_video_target = QComboBox()
            self.combo_video_target.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            self.combo_video_target.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            # "Same as original" always first — the default, and what replaces
            # the earlier behavior of silently auto-picking a matching format
            # behind the user's back on every dialog open (see
            # object_actions._show_converted_import_settings_dialog's own
            # comment on why that was removed): an explicit, rememberable
            # choice in the dropdown itself, resolved at import time to
            # whichever real target matches the object's own current
            # container — see accept()/_resolve_final_video_target() for what
            # happens when it doesn't match either of the two real ones.
            self.combo_video_target.addItem(tr("Оригинальный"), "original")
            for key, spec in video_transcode.TRANSCODE_TARGETS.items():
                self.combo_video_target.addItem(spec["label"], key)
            idx = self.combo_video_target.findData(current_values.get("video_transcode_target", "original"))
            self.combo_video_target.setCurrentIndex(idx if idx >= 0 else 0)
            self.combo_video_target.currentIndexChanged.connect(self._on_video_target_changed)
            options_layout.addWidget(self.combo_video_target)

            # Real reported concern: "Как в оригинале" resolves silently on the
            # common (matching-container) path — without this, the user never
            # sees WHICH concrete format actually gets used until something
            # goes wrong (the unresolvable case, which already prompts). A
            # silent wrong auto-pick — e.g. this object's own m_OriginalPath
            # having drifted from an earlier, differently-formatted import —
            # would otherwise be invisible until the encoded result plays back
            # wrong. Shown/hidden by _update_video_target_resolved_label(),
            # never for a concrete (non-"original") combo choice, where
            # there's no ambiguity to begin with.
            self.label_video_target_resolved = QLabel()
            self.label_video_target_resolved.setWordWrap(True)
            options_layout.addWidget(self.label_video_target_resolved)
            self._update_video_target_resolved_label()

            video_quality_label_row = QHBoxLayout()
            video_quality_label_row.addWidget(QLabel(tr("Качество:")))
            video_quality_widget, self.slider_video_quality, video_quality_help = build_audio_quality_slider(
                int(current_values.get("video_transcode_quality", 70)), help_icon=True
            )
            video_quality_label_row.addWidget(video_quality_help)
            video_quality_label_row.addStretch(1)
            options_layout.addLayout(video_quality_label_row)
            options_layout.addWidget(video_quality_widget)

            # Real reported complaint: this dialog felt cluttered — the
            # always-visible explanation of what happens to the saved file
            # was moved behind a "(?)" hover icon (_make_help_icon(), same
            # pattern app_settings_dialog.py already uses for
            # cb_resource_custom's own tooltip) next to the label instead of
            # its own separate wrapped-text line below the path row.
            path_label_row = QHBoxLayout()
            path_label_row.addWidget(QLabel(tr("Сохранить результат в:")))
            path_label_row.addWidget(_make_help_icon(
                tr("Результат сохраняется на диск как обычный файл — в следующий раз можно выбрать уже готовый файл "
                   "вместо повторного транскодирования.")
            ))
            path_label_row.addStretch(1)
            options_layout.addLayout(path_label_row)
            path_row = QHBoxLayout()
            self.edit_video_output_path = QLineEdit()
            self.edit_video_output_path.setReadOnly(True)
            path_row.addWidget(self.edit_video_output_path, 1)
            browse_btn = QPushButton(tr("Обзор..."))
            browse_btn.clicked.connect(self._browse_video_output_path)
            path_row.addWidget(browse_btn)
            options_layout.addLayout(path_row)

            video_layout.addWidget(options_widget)
            video_layout.addStretch(1)
            outer.addWidget(video_box)

            self._suggest_video_output_path()
            self._on_video_transcode_toggled(False)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        outer.addWidget(btn_box)

        # Real reported bug: this dialog never sized itself at construction
        # time, so .exec() showed it at whatever undersized default Qt falls
        # back to instead of its true natural size — confirmed directly:
        # self.size() right after __init__ was a bogus 22x22 while
        # self.sizeHint() already correctly reported the real size.
        self.layout().activate()
        self.adjustSize()

    def _update_manual_format_visibility(self) -> None:
        is_manual = self.combo_format_mode.currentData() == "manual"
        self.combo_manual_format.setVisible(is_manual)
        self._format_warning_label.setVisible(is_manual and bool(self._format_warning_label.text()))

        # See ApplicationSettingsDialog's _grow_to_fit() for the full,
        # empirically-confirmed root cause (a genuine Qt/Windows platform
        # issue, not something fixable by rearranging activate()/adjustSize()
        # calls: an already-shown top-level dialog's real native window can
        # get permanently stuck at its first-shown size, refusing to shrink
        # even via a raw win32 SetWindowPos() call from outside Qt entirely)
        # — grow-only resizing is the only reliable fix found. This dialog's
        # own earlier verification here was only ever done via
        # QT_QPA_PLATFORM=offscreen (see __init__'s docstring comment), which
        # never exercises a real native resize at all, so the same
        # distortion bug could easily have gone unnoticed here too.
        if self._texture_box is not None:
            self._texture_box.layout().activate()
        self.layout().activate()
        _grow_to_fit(self)

    def _on_format_choice_changed(self) -> None:
        warning = None
        if self.combo_format_mode.currentData() == "manual":
            warning = texture_format_platform_warning(self.combo_manual_format.currentData(), self._platform)
        self._format_warning_label.setText(warning or "")
        self._update_manual_format_visibility()

    def _on_video_transcode_toggled(self, checked: bool) -> None:
        self._video_transcode_options_widget.setVisible(checked)
        self._video_transcode_options_widget.layout().activate()
        self.layout().activate()
        _grow_to_fit(self)

    def _on_video_target_changed(self) -> None:
        # Only re-suggests the extension if the field still holds an
        # AUTO-suggested path (i.e. the user hasn't picked their own via
        # Browse yet) — never overwrites a real, deliberate user choice just
        # because they changed their mind about the codec afterward.
        if self._video_output_path_is_suggested:
            self._suggest_video_output_path()
        self._update_video_target_resolved_label()

    def _update_video_target_resolved_label(self) -> None:
        """Keeps the "→ ..." note under the format dropdown in sync with
        whatever "Как в оригинале" would ACTUALLY resolve to right now — see
        the widget's own construction comment for why this exists at all.
        Hidden entirely for a concrete (non-"original") choice, since there's
        nothing ambiguous to explain there."""
        if self.combo_video_target.currentData() != "original":
            self.label_video_target_resolved.setVisible(False)
            return
        if self._resolved_original_target is not None:
            label = video_transcode.TRANSCODE_TARGETS[self._resolved_original_target]["label"]
            text = f"→ {label}"
        elif self._obj is not None:
            text = tr("→ формат этого видео не совпадает ни с одним из целевых форматов — при импорте будет предложено выбрать")
        else:
            text = tr("→ будет подобран отдельно для каждого объекта при импорте")
        self.label_video_target_resolved.setText(text)
        self.label_video_target_resolved.setVisible(True)
        self.layout().activate()
        _grow_to_fit(self)

    def _cosmetic_video_target_key(self) -> str:
        """Resolves the combo's current selection to a REAL TRANSCODE_TARGETS
        key for cosmetic purposes only (the suggested output filename's
        extension, and the Browse dialog's file-type filter) — never used to
        decide what actually gets passed to import_object_converted(), which
        goes through _resolve_final_video_target() instead (see accept()).
        "Same as original" resolves to whatever this object's own current
        container maps to when known; falls back to the first real target
        otherwise (bulk selection with no single object, or an object whose
        original container isn't one of the two anyway) — purely a
        placeholder guess for the filename, since the real resolution/
        fallback-confirmation happens in accept()."""
        target_key = self.combo_video_target.currentData() or "original"
        if target_key != "original":
            return target_key
        return self._resolved_original_target or next(iter(video_transcode.TRANSCODE_TARGETS))

    def _suggest_video_output_path(self) -> None:
        ext = video_transcode.TRANSCODE_TARGETS[self._cosmetic_video_target_key()]["container_ext"]
        if self._source_file_path is not None:
            suggested = self._source_file_path.with_name(self._source_file_path.stem + "_transcoded" + ext)
        else:
            suggested = Path.cwd() / f"transcoded{ext}"
        self.edit_video_output_path.setText(str(suggested))
        self._video_output_path_is_suggested = True

    def _browse_video_output_path(self) -> None:
        spec = video_transcode.TRANSCODE_TARGETS[self._cosmetic_video_target_key()]
        start_path = self.edit_video_output_path.text() or str(Path.cwd() / f"transcoded{spec['container_ext']}")
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Сохранить транскодированное видео как..."), start_path,
            f"{spec['label']} (*{spec['container_ext']});;" + tr("Все файлы (*)"),
        )
        if path:
            self.edit_video_output_path.setText(path)
            self._video_output_path_is_suggested = False

    def accept(self) -> None:
        if self.cb_video_transcode is not None and self.cb_video_transcode.isChecked():
            if not self.edit_video_output_path.text().strip():
                QMessageBox.warning(
                    self, tr("Не указан путь"),
                    tr("Транскодирование включено, но не выбран путь для сохранения результата."),
                )
                return
            # "Same as original" but this object's own container isn't one of
            # the two real transcode targets (only checked when a single
            # object is actually known — see __init__'s own comment on why a
            # bulk selection can't answer this here at all, and defers to
            # import_object_converted()'s own per-object fallback instead).
            # Asked here, not earlier, so it happens exactly once, right
            # before the choice is actually locked in, and "No" just leaves
            # the user in the dialog to pick a concrete format themselves
            # instead of aborting the whole import outright.
            if (self.combo_video_target.currentData() == "original"
                    and self._obj is not None and self._resolved_original_target is None):
                fallback_key = next(iter(video_transcode.TRANSCODE_TARGETS))
                fallback_label = video_transcode.TRANSCODE_TARGETS[fallback_key]["label"]
                reply = QMessageBox.question(
                    self, tr("Оригинальный формат не поддерживается"),
                    tr("Оригинальный формат этого видео нельзя транскодировать напрямую — он не входит в число целевых "
                       "форматов транскодирования ({join}). Использовать вместо этого «{fallback_label}» для этого "
                       "импорта?", join=', '.join((spec['label'] for spec in video_transcode.TRANSCODE_TARGETS.values())), fallback_label=fallback_label),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
                self._original_fallback_target = fallback_key
                self._update_video_target_resolved_label()
        super().accept()

    def _resolve_final_video_target(self) -> str:
        """The target actually passed to import_object_converted() — as
        opposed to the combo's own raw selection (values["video_transcode_target"],
        persisted to CONFIG as-is so "Same as original" stays the remembered
        choice for the NEXT clip even when THIS one needed a one-off
        fallback). A concrete combo choice (h264/vp8) passes through
        unchanged; "original" resolves to whatever accept() already worked
        out (self._original_fallback_target if the user just confirmed one,
        else self._resolved_original_target if this object's own container
        matched directly) — or, for a bulk selection with no single object
        known here at all, is left as the literal "original" sentinel for
        import_object_converted() to resolve per-object at actual import
        time instead (see that function's own VideoClip-branch comment)."""
        target_key = self.combo_video_target.currentData() or "original"
        if target_key != "original":
            return target_key
        return self._original_fallback_target or self._resolved_original_target or "original"

    def get_values(self) -> dict:
        values = {}
        if self.combo_format_mode is not None:
            values["texture_import_format_mode"] = self.combo_format_mode.currentData()
        if self.combo_manual_format is not None:
            values["texture_import_manual_format"] = self.combo_manual_format.currentData()
        if self.cb_mipmaps is not None:
            values["texture_import_mipmaps"] = self.cb_mipmaps.isChecked()
        if self.slider_audio_quality is not None:
            values["audio_import_quality"] = self.slider_audio_quality.value()
        if self.cb_video_transcode is not None:
            values["video_transcode"] = self.cb_video_transcode.isChecked()
            values["video_transcode_target"] = self.combo_video_target.currentData()
            values["video_transcode_resolved_target"] = self._resolve_final_video_target()
            values["video_transcode_quality"] = self.slider_video_quality.value()
            values["video_transcode_output_path"] = self.edit_video_output_path.text().strip() or None
        return values
