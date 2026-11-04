"""Audio and video preview widgets and the seek slider they share."""

from core.i18n import tr
import os
import tempfile
from pathlib import Path
from typing import Optional
from PyQt6.QtCore import QEvent, Qt, QSize, QUrl
from PyQt6.QtGui import QFont
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QSlider, QStyle, QToolButton, QVBoxLayout, QWidget
import preview_icons
import theme
from core.file_utils import format_size

from gui_common import _mute_button_icon, _refresh_transport_icons, _transport_icon_color, reapply_elided_labels, set_elided_label_text


class ClickableSeekSlider(QSlider):
    """A horizontal QSlider that jumps to (and starts dragging from) whatever
    position on the bar was clicked, instead of Qt's default QSlider behavior —
    a click anywhere except precisely on the small handle only page-steps by
    one increment, and dragging only works once already grabbing the handle
    itself. Real reported UX gap for the audio/video preview widgets' seek
    bars: clicking anywhere else on the (much larger) bar area either did
    nothing useful or required first finding and dragging the thin handle.

    Reimplements press/move/release entirely rather than layering on top of
    QSlider's own (private, C++-side) drag bookkeeping — computing the target
    value from the click/drag position and emitting the same sliderPressed/
    sliderMoved/sliderReleased signals QSlider already emits natively, so
    every existing caller (AudioPreviewWidget/VideoPreviewWidget's own
    _on_seek_pressed/_on_seek_moved/_on_seek_released) keeps working
    unchanged — this widget is a drop-in QSlider replacement, not a new API."""

    def _value_from_pos(self, x: int) -> int:
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), x, self.width())

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        value = self._value_from_pos(round(event.position().x()))
        self.setValue(value)
        self.sliderPressed.emit()
        self.sliderMoved.emit(value)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        value = self._value_from_pos(round(event.position().x()))
        self.setValue(value)
        self.sliderMoved.emit(value)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        self.sliderReleased.emit()
        event.accept()


class AudioPreviewWidget(QWidget):
    """In-process audio playback (QMediaPlayer/QAudioOutput) for AudioClip rows —
    no external player or subprocess involved, unlike the reference implementation
    this feature was ported from (which shelled out to afplay/PowerShell), since
    QtMultimedia is already available wherever PyQt6 itself is.

    A single circular accent-colored Play/Pause button (icon swaps between the two
    states, matching how basically every modern media player does it — the
    original two-separate-buttons layout was a leftover from the AssetStudioGUI
    control set this was first ported from, not a deliberate choice) plus a
    smaller Stop button, a seek slider flanked by live time labels, a compact
    volume slider, and a loop toggle — icon-first throughout (Qt's own standard
    icons, no new asset files needed) instead of the original's plain text
    buttons ("Воспроизвести"/"Пауза"/"Стоп"), which read as a rough first draft
    next to the rest of the app's now-styled controls."""

    _ICON_SIZE = 20
    # theme.py's #AccentRoundButton/#RoundToolButton border-radius (22px/16px) is
    # hardcoded to exactly half of these two sizes to render as a true circle —
    # change one, change the other.
    _PLAY_BTN_SIZE = 44
    _SMALL_BTN_SIZE = 32

    def __init__(self, parent=None):
        super().__init__(parent)
        self._temp_file: Optional[Path] = None
        # Real fallback (not None) so a selection made before PreviewPanel's
        # first apply_theme_colors() call still renders transport icons
        # correctly — same ordering hazard already hit once for
        # VideoPreviewWidget/MetadataPanel (see their own comments).
        self._colors = theme.get_colors(theme.load_saved_theme_name())
        self._seeking = False  # true while the user is dragging the seek slider —
        # suppresses positionChanged from fighting the drag (same reasoning as
        # AssetStudioGUI's FMODprogressBar_MouseDown/_MouseUp bracketing).

        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        # Same manual-loop fix as VideoPreviewWidget (see its __init__ comment
        # for the full root-cause writeup, confirmed via live playback
        # testing): QMediaPlayer.Loops.Infinite loops internally in the
        # backend without emitting EndOfMedia for any loop but the last one,
        # so a real "stop as soon as the checkbox is unchecked" needs looping
        # done manually here instead of delegated to the backend at all.
        self._player.setLoops(QMediaPlayer.Loops.Once)
        self._player.mediaStatusChanged.connect(self._on_media_status_changed)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)
        layout.setContentsMargins(24, 16, 24, 16)

        # A long sample/clip name (unbounded, unlike the fixed control widths below)
        # would otherwise force this whole widget — and with it the whole Preview
        # tab's left pane — wide enough to show it on one line; elided-with-tooltip
        # (same helper set_elided_label_text()/reapply_elided_labels() use
        # elsewhere in this module) instead caps it at whatever width the rest of
        # the layout actually needs.
        self._label = QLabel(tr("Аудио не загружено"))
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = self._label.font()
        title_font.setPointSize(title_font.pointSize() + 1)
        title_font.setBold(True)
        self._label.setFont(title_font)
        layout.addWidget(self._label)

        self._info_label = QLabel("")
        self._info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._info_label.setObjectName("MutedCaption")
        layout.addWidget(self._info_label)

        seek_row = QHBoxLayout()
        seek_row.setSpacing(8)
        self._time_current_label = QLabel("0:00")
        self._time_current_label.setObjectName("MutedCaption")
        self._seek_slider = ClickableSeekSlider(Qt.Orientation.Horizontal)
        self._seek_slider.setRange(0, 0)
        # A fixed width (not just a minimum) meant the panel could never be made
        # any narrower than this slider, regardless of how much the user shrank the
        # splitter — a floor, not a preference. Minimum-only lets it (and the panel
        # around it) shrink further while still keeping the slider usable.
        self._seek_slider.setMinimumWidth(80)
        self._seek_slider.sliderPressed.connect(self._on_seek_pressed)
        self._seek_slider.sliderMoved.connect(self._on_seek_moved)
        self._seek_slider.sliderReleased.connect(self._on_seek_released)
        self._time_total_label = QLabel("0:00")
        self._time_total_label.setObjectName("MutedCaption")
        seek_row.addWidget(self._time_current_label)
        seek_row.addWidget(self._seek_slider, 1)
        seek_row.addWidget(self._time_total_label)
        layout.addLayout(seek_row)

        controls = QHBoxLayout()
        controls.setSpacing(12)
        controls.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._loop_btn = QToolButton()
        self._loop_btn.setCheckable(True)
        self._loop_btn.setIcon(preview_icons.get_transport_icon("loop", _transport_icon_color(self._colors, "loop")))
        self._loop_btn.setIconSize(QSize(self._ICON_SIZE - 4, self._ICON_SIZE - 4))
        self._loop_btn.setFixedSize(self._SMALL_BTN_SIZE, self._SMALL_BTN_SIZE)
        self._loop_btn.setToolTip(tr("Повтор"))
        self._loop_btn.setObjectName("RoundToolButton")
        self._loop_btn.toggled.connect(self._on_loop_toggled)
        controls.addWidget(self._loop_btn)

        self._play_pause_btn = QToolButton()
        self._play_pause_btn.setIcon(preview_icons.get_transport_icon("play", _transport_icon_color(self._colors, "play")))
        # Same fill ratio loop/stop use (icon_size-4 within their own button
        # size) instead of reusing _ICON_SIZE directly — real reported bug
        # (video's fullscreen mode, but the same proportion applies here):
        # a play icon sized the same as the small buttons' fills a visibly
        # SMALLER fraction of its own bigger _PLAY_BTN_SIZE button.
        play_icon_size = round((self._ICON_SIZE - 4) / self._SMALL_BTN_SIZE * self._PLAY_BTN_SIZE)
        self._play_pause_btn.setIconSize(QSize(play_icon_size, play_icon_size))
        self._play_pause_btn.setFixedSize(self._PLAY_BTN_SIZE, self._PLAY_BTN_SIZE)
        self._play_pause_btn.setToolTip(tr("Воспроизвести"))
        self._play_pause_btn.setObjectName("AccentRoundButton")
        self._play_pause_btn.clicked.connect(self._toggle_play_pause)
        controls.addWidget(self._play_pause_btn)

        self._stop_btn = QToolButton()
        self._stop_btn.setIcon(preview_icons.get_transport_icon("stop", _transport_icon_color(self._colors, "stop")))
        self._stop_btn.setIconSize(QSize(self._ICON_SIZE - 4, self._ICON_SIZE - 4))
        self._stop_btn.setFixedSize(self._SMALL_BTN_SIZE, self._SMALL_BTN_SIZE)
        self._stop_btn.setToolTip(tr("Стоп"))
        self._stop_btn.setObjectName("RoundToolButton")
        self._stop_btn.clicked.connect(self._player.stop)
        controls.addWidget(self._stop_btn)
        layout.addLayout(controls)

        # NoFocus on all three — a QToolButton defaults to StrongFocus, so clicking
        # one moved keyboard focus onto the button itself, which meant Up/Down
        # afterwards stopped navigating the main table (whatever had focus before)
        # until the user clicked a row again. None of these need keyboard focus of
        # their own; NoFocus lets a click just click without disturbing focus
        # elsewhere in the app.
        for _btn in (self._loop_btn, self._play_pause_btn, self._stop_btn):
            _btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        volume_row = QHBoxLayout()
        volume_row.setSpacing(6)
        # QHBoxLayout stretches a sub-layout added via addLayout() to the FULL row
        # width regardless of the outer layout's own AlignCenter (that only affects
        # widgets added directly to it) — without explicit stretches on both sides
        # here, the icon and slider ended up pinned to the row's opposite edges
        # with a large empty gap between them instead of sitting together as one
        # compact, centered control.
        volume_row.addStretch(1)
        self._mute_btn = QToolButton()
        self._mute_btn.setIcon(_mute_button_icon(self._colors, muted=False))
        self._mute_btn.setIconSize(QSize(16, 16))
        self._mute_btn.setAutoRaise(True)
        self._mute_btn.setToolTip(tr("Выключить звук"))
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._mute_btn.clicked.connect(self._toggle_mute)
        volume_row.addWidget(self._mute_btn)
        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(100)
        # Minimum, not fixed — a fixed width here would reintroduce the exact hard
        # floor on how far the whole Preview pane can be shrunk that this slider
        # used to cause (see seek_slider's comment above for the same reasoning).
        # Fixed size POLICY though (a QSlider defaults to Expanding horizontally),
        # so it doesn't try to grab the row's leftover space itself — the two
        # addStretch() calls are what center the icon+slider pair instead.
        self._volume_slider.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._volume_slider.setMinimumWidth(60)
        self._volume_slider.setMaximumWidth(100)
        self._volume_slider.valueChanged.connect(self._on_volume_changed)
        volume_row.addWidget(self._volume_slider)
        volume_row.addStretch(1)
        layout.addLayout(volume_row)

        self._set_controls_enabled(False)

    def apply_theme_colors(self, colors) -> None:
        """Called by PreviewPanel.apply_theme_colors() alongside the other
        preview widgets — keeps the transport icons' colors in sync with a
        live theme toggle (see _transport_icon_color's own docstring for why
        play/pause and stop/loop resolve to different theme roles)."""
        self._colors = colors
        _refresh_transport_icons(colors, self._player, self._play_pause_btn, self._stop_btn, self._loop_btn)
        self._mute_btn.setIcon(_mute_button_icon(colors, self._audio_output.isMuted()))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        reapply_elided_labels(self._label, self._info_label)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for w in (self._play_pause_btn, self._stop_btn, self._seek_slider, self._loop_btn):
            w.setEnabled(enabled)

    def set_audio(self, samples: dict, name: str, info_text: str = "", autoplay: bool = False) -> None:
        self._player.stop()
        self._cleanup_temp_file()

        if not samples:
            set_elided_label_text(self._label, tr("{name}: аудиосэмплы не найдены", name=name))
            set_elided_label_text(self._info_label, "")
            self._set_controls_enabled(False)
            return

        sample_name, data = next(iter(samples.items()))
        suffix = Path(sample_name).suffix or ".wav"
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        self._temp_file = Path(path)

        set_elided_label_text(self._label, name)
        # Not sample_name itself — Unity embeds the sample under (essentially) the
        # same name as the clip, just with a file extension added, so showing both
        # in full was just the same name twice in a row. The extension alone still
        # says everything sample_name was actually adding here.
        suffix = Path(sample_name).suffix.lstrip(".").upper()
        info_parts = [p for p in (suffix, format_size(len(data)), info_text) if p]
        set_elided_label_text(self._info_label, "  ·  ".join(info_parts))
        self._set_controls_enabled(True)
        self._player.setSource(QUrl.fromLocalFile(str(self._temp_file)))
        self._seek_slider.setValue(0)
        self._update_time_label(0, 0)
        # CONFIG.autoplay_audio (Вид menu) — off by default, so a scroll
        # through a table full of AudioClips doesn't blast sound on every
        # row without being asked to.
        if autoplay:
            self._player.play()

    def _toggle_mute(self) -> None:
        # QAudioOutput's own mute flag, not "remember the volume and set it to 0" —
        # a real independent on/off that leaves the slider (and the volume level
        # it'll go back to on unmute) alone.
        muted = not self._audio_output.isMuted()
        self._audio_output.setMuted(muted)
        icon = _mute_button_icon(self._colors, muted)
        self._mute_btn.setIcon(icon)
        self._mute_btn.setToolTip(tr("Включить звук") if muted else tr("Выключить звук"))

    def _toggle_play_pause(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _on_loop_toggled(self, checked: bool) -> None:
        # No longer touches self._player.setLoops() — see __init__'s comment;
        # looping is handled by _on_media_status_changed re-reading this
        # checkbox's current state at the moment playback actually ends.
        # Icon color still needs to follow the checked state, though — see
        # _transport_icon_color's own docstring for why.
        self._loop_btn.setIcon(
            preview_icons.get_transport_icon("loop", _transport_icon_color(self._colors, "loop", checked))
        )

    def _on_media_status_changed(self, status) -> None:
        if status != QMediaPlayer.MediaStatus.EndOfMedia:
            return
        if self._loop_btn.isChecked():
            self._player.setPosition(0)
            self._player.play()
        else:
            self._player.stop()

    def _on_volume_changed(self, value: int) -> None:
        self._audio_output.setVolume(value / 100.0)

    def _on_state_changed(self, state) -> None:
        # Single button whose icon/tooltip reflects what clicking it will do NEXT
        # (as opposed to what's happening now) — "Play" while paused/stopped,
        # "Pause" while playing — matching ordinary media-player conventions.
        is_playing = state == QMediaPlayer.PlaybackState.PlayingState
        icon_kind = "pause" if is_playing else "play"
        self._play_pause_btn.setIcon(preview_icons.get_transport_icon(icon_kind, _transport_icon_color(self._colors, icon_kind)))
        self._play_pause_btn.setToolTip(tr("Пауза") if is_playing else tr("Воспроизвести"))
        if state == QMediaPlayer.PlaybackState.StoppedState and not self._seeking:
            self._seek_slider.setValue(0)
            self._update_time_label(0, self._player.duration())

    def _on_position_changed(self, position_ms: int) -> None:
        if self._seeking:
            return
        self._seek_slider.setValue(position_ms)
        self._update_time_label(position_ms, self._player.duration())

    def _on_duration_changed(self, duration_ms: int) -> None:
        self._seek_slider.setRange(0, duration_ms)
        self._update_time_label(self._player.position(), duration_ms)

    def _on_seek_pressed(self) -> None:
        self._seeking = True

    def _on_seek_moved(self, position_ms: int) -> None:
        self._update_time_label(position_ms, self._player.duration())

    def _on_seek_released(self) -> None:
        self._player.setPosition(self._seek_slider.value())
        self._seeking = False

    @staticmethod
    def _format_ms(ms: int) -> str:
        total_seconds = max(0, ms) // 1000
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}:{seconds:02d}"

    def _update_time_label(self, position_ms: int, duration_ms: int) -> None:
        self._time_current_label.setText(self._format_ms(position_ms))
        self._time_total_label.setText(self._format_ms(duration_ms))

    def _cleanup_temp_file(self) -> None:
        if self._temp_file is not None and self._temp_file.exists():
            try:
                self._temp_file.unlink()
            except OSError:
                pass
        self._temp_file = None

    def stop_playback(self) -> None:
        """Stops playback without touching the loaded source/temp file — call this
        when the selection switches to something else entirely (not necessarily
        another AudioClip), so a still-playing track doesn't keep going in the
        background after the Preview tab has already moved on. Distinct from
        cleanup(), which additionally drops the source and removes the temp file —
        that one's for app shutdown, this one's for "just stop, we might come back
        to an AudioClip again shortly and set_audio() will handle it then"."""
        self._player.stop()

    def cleanup(self) -> None:
        """Stop playback and remove the temp file — called when the app closes or
        the panel is otherwise torn down, mirroring how other per-selection temp
        resources in this app are cleaned up."""
        self._player.stop()
        self._player.setSource(QUrl())
        self._cleanup_temp_file()


class VideoPreviewWidget(QWidget):
    """In-process video playback for VideoClip rows — same QMediaPlayer/
    QAudioOutput stack AudioPreviewWidget already uses, plus QVideoWidget
    (PyQt6.QtMultimediaWidgets) for the picture itself. Adds no new dependency:
    PyQt6's own QtMultimedia backend (confirmed directly — see
    PyQt6/Qt6/plugins/multimedia/ffmpegmediaplugin.dll and the avcodec/avformat/
    swresample/swscale DLLs alongside it) already bundles the FFmpeg-based
    decoder audio preview depends on, and that same decoder handles video
    demuxing/decoding too — the only genuinely new piece is the QVideoWidget
    output sink, a plain Qt widget, not a binary dependency.

    Same control set and layout shape as AudioPreviewWidget (title/info labels,
    seek slider with time labels, loop/play-pause/stop row, volume row) plus the
    video surface itself — deliberately mirrored rather than redesigned, per the
    request that this look like "the same advanced and stylish widget" as the
    audio one.

    Fullscreen note (a real reported issue with the first version of this
    widget): QVideoWidget.setFullScreen() only fullscreens the bare video
    SURFACE — every OTHER control here (seek bar, play/pause, volume, labels)
    is a SIBLING widget in the same layout, not a child of the video widget, so
    going fullscreen that way left literally nothing but a black rectangle with
    no way to pause, seek, or even get back out except guessing at Escape.
    Fixed by NOT using that method at all: everything below the header
    (seek row, transport buttons, volume, and the fullscreen toggle itself) is
    built into one container widget (_controls_widget) that gets reparented
    together with _video_widget into a real top-level fullscreen window on
    entry, and both are moved back into their normal spots in this widget's own
    layout on exit — so the fullscreen view is playable, not just watchable."""

    _ICON_SIZE = 20
    _PLAY_BTN_SIZE = 44
    _SMALL_BTN_SIZE = 32

    def __init__(self, parent=None):
        super().__init__(parent)
        self._temp_file: Optional[Path] = None
        self._seeking = False
        self._fullscreen_window: Optional[QWidget] = None
        # Real fallback (not None) so fullscreen entered before PreviewPanel's
        # first apply_theme_colors() call still renders correctly — see the
        # MetadataPanel "nothing called it on startup" bug this project already
        # hit once for the same ordering hazard.
        self._colors = theme.get_colors(theme.load_saved_theme_name())

        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)
        self._video_widget = QVideoWidget()
        self._player.setVideoOutput(self._video_widget)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        # Real reported bug, confirmed by live testing against a real decoded
        # video (not a synthetic status callback): QMediaPlayer.Loops.Infinite
        # loops INTERNALLY inside the backend and never emits mediaStatusChanged
        # EndOfMedia for any loop but the very last one — so a "backstop" that
        # only reacts to EndOfMedia can't intercept an in-progress Infinite
        # loop at all; it can only catch whatever end the backend eventually
        # reaches after setLoops(Once) happens to take effect, which measured
        # 3 extra loop iterations after disabling repeat in one real test run.
        # Confirmed via QMediaPlayer.Loops.Infinite genuinely NOT being usable
        # for "stop as soon as the checkbox is unchecked" semantics regardless
        # of any backstop built on top of it.
        #
        # Fix: never ask the backend to loop at all (always Loops.Once, set
        # once here and never changed) — loop is instead implemented manually
        # by restarting from position 0 in _on_media_status_changed's own
        # EndOfMedia handler, which re-reads the loop checkbox's CURRENT state
        # every time media genuinely ends. EndOfMedia now always fires (since
        # the backend never auto-loops), so there is no backend-internal state
        # left to race against — unchecking the box takes effect the very next
        # time playback reaches the end, full stop, verified with a real
        # (ffmpeg-encoded, not synthetic) multi-loop live-playback test that
        # deliberately disabled repeat mid-loop and confirmed zero further
        # loop restarts.
        self._player.setLoops(QMediaPlayer.Loops.Once)
        self._player.mediaStatusChanged.connect(self._on_media_status_changed)

        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(10)
        self._layout.setContentsMargins(12, 12, 12, 16)

        # Item 0 — stays in this widget's own layout even while fullscreen
        # (only _video_widget and _controls_widget travel); a real reported
        # request just wants labels/controls to survive fullscreen at all, not
        # necessarily the title specifically, but the fullscreen window's own
        # setWindowTitle() below at least surfaces it via the OS/taskbar.
        self._label = QLabel(tr("Видео не загружено"))
        title_font = self._label.font()
        title_font.setPointSize(title_font.pointSize() + 1)
        title_font.setBold(True)
        self._label.setFont(title_font)
        self._layout.addWidget(self._label)
        self._info_label = QLabel("")
        self._info_label.setObjectName("MutedCaption")
        self._layout.addWidget(self._info_label)

        # Item 1 — QVideoWidget has its own solid-black backdrop by default (no
        # picture until a source with a video track is playing) — Expanding so
        # it claims whatever space the Preview tab's stack gives this page,
        # same as ImagePreviewWidget's own graphics view does for images.
        self._video_widget.setMinimumHeight(160)
        self._video_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._layout.addWidget(self._video_widget, 1)

        # Item 2 — everything below the video. Built as three independently
        # reparentable WIDGETS (_seek_widget/_transport_widget/_volume_widget),
        # not just bare layouts, specifically so fullscreen can lay them out
        # DIFFERENTLY (transport left / volume+fullscreen right, the
        # conventional player arrangement — a real reported request, since the
        # embedded panel's own stacked-and-centered arrangement reads as
        # sparse and disorganized once stretched across a real fullscreen
        # width) while every button stays the exact same instance either way.
        self._seek_widget = QWidget()
        seek_row = QHBoxLayout(self._seek_widget)
        seek_row.setContentsMargins(0, 0, 0, 0)
        seek_row.setSpacing(8)
        self._time_current_label = QLabel("0:00")
        self._time_current_label.setObjectName("MutedCaption")
        self._base_time_font = self._time_current_label.font()
        self._seek_slider = ClickableSeekSlider(Qt.Orientation.Horizontal)
        self._seek_slider.setRange(0, 0)
        self._seek_slider.setMinimumWidth(80)
        self._seek_slider.sliderPressed.connect(self._on_seek_pressed)
        self._seek_slider.sliderMoved.connect(self._on_seek_moved)
        self._seek_slider.sliderReleased.connect(self._on_seek_released)
        self._time_total_label = QLabel("0:00")
        self._time_total_label.setObjectName("MutedCaption")
        seek_row.addWidget(self._time_current_label)
        seek_row.addWidget(self._seek_slider, 1)
        seek_row.addWidget(self._time_total_label)

        self._transport_widget = QWidget()
        transport_row = QHBoxLayout(self._transport_widget)
        transport_row.setContentsMargins(0, 0, 0, 0)
        transport_row.setSpacing(12)

        self._loop_btn = QToolButton()
        self._loop_btn.setCheckable(True)
        self._loop_btn.setIcon(preview_icons.get_transport_icon("loop", _transport_icon_color(self._colors, "loop")))
        self._loop_btn.setToolTip(tr("Повтор"))
        self._loop_btn.setObjectName("RoundToolButton")
        self._loop_btn.toggled.connect(self._on_loop_toggled)
        transport_row.addWidget(self._loop_btn)

        self._play_pause_btn = QToolButton()
        self._play_pause_btn.setIcon(preview_icons.get_transport_icon("play", _transport_icon_color(self._colors, "play")))
        self._play_pause_btn.setToolTip(tr("Воспроизвести"))
        self._play_pause_btn.setObjectName("AccentRoundButton")
        self._play_pause_btn.clicked.connect(self._toggle_play_pause)
        transport_row.addWidget(self._play_pause_btn)

        self._stop_btn = QToolButton()
        self._stop_btn.setIcon(preview_icons.get_transport_icon("stop", _transport_icon_color(self._colors, "stop")))
        self._stop_btn.setToolTip(tr("Стоп"))
        self._stop_btn.setObjectName("RoundToolButton")
        self._stop_btn.clicked.connect(self._player.stop)
        transport_row.addWidget(self._stop_btn)

        for _btn in (self._loop_btn, self._play_pause_btn, self._stop_btn):
            _btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._volume_widget = QWidget()
        volume_row = QHBoxLayout(self._volume_widget)
        volume_row.setContentsMargins(0, 0, 0, 0)
        volume_row.setSpacing(6)
        self._mute_btn = QToolButton()
        self._mute_btn.setIcon(_mute_button_icon(self._colors, muted=False))
        self._mute_btn.setAutoRaise(True)
        self._mute_btn.setToolTip(tr("Выключить звук"))
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._mute_btn.clicked.connect(self._toggle_mute)
        volume_row.addWidget(self._mute_btn)
        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(100)
        self._volume_slider.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._volume_slider.setMinimumWidth(60)
        self._volume_slider.valueChanged.connect(self._on_volume_changed)
        volume_row.addWidget(self._volume_slider)

        self._fullscreen_btn = QToolButton()
        # Real reported bug: get_zoom_icon() draws its own colored chip
        # backdrop (the same style the plain-QPushButton preview toolbar
        # uses, e.g. TextureZoomDialog's popup button) — sitting that INSIDE
        # this button's own RoundToolButton QSS circle produced exactly the
        # "chip stuck inside a circle" look _draw_glyph_icon's own docstring
        # already warns about, confirmed by rendering the real button and
        # looking at it, not just reading the code. get_transport_icon's
        # flat, theme-matched, backdrop-less style — already used correctly
        # for _stop_btn/_loop_btn right below, the SAME RoundToolButton style
        # — fixes it the same way.
        self._fullscreen_btn.setIcon(
            preview_icons.get_transport_icon("expand", _transport_icon_color(self._colors, "expand"))
        )
        self._fullscreen_btn.setToolTip(tr("На весь экран"))
        self._fullscreen_btn.setObjectName("RoundToolButton")
        self._fullscreen_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._fullscreen_btn.clicked.connect(self._toggle_fullscreen)

        # --- Normal (embedded-panel) arrangement: stacked, centered — the
        # narrow Preview-tab width this was originally designed for. Built
        # once here; _enter_fullscreen()/_exit_fullscreen() below move the
        # SAME sub-widgets (plus _fullscreen_btn) into/out of a different
        # arrangement via _rebuild_bottom_row(), they never get rebuilt
        # themselves — only which row layout currently contains them changes.
        #
        # Real reported bug: at fullscreen's much larger control sizes, this
        # normal-mode arrangement (transport on its own row, volume+fullscreen
        # stacked on a second row below it) wastes a disproportionate strip of
        # screen height on the volume control alone. _rebuild_bottom_row()
        # below switches to a single combined row (transport left, volume+
        # fullscreen pinned right — the conventional player arrangement) once
        # _bottom_fullscreen is set, cutting one whole row of vertical space.
        self._controls_widget = QWidget()
        self._controls_layout = QVBoxLayout(self._controls_widget)
        self._controls_layout.setContentsMargins(0, 0, 0, 0)
        self._controls_layout.setSpacing(10)
        self._controls_layout.addWidget(self._seek_widget)
        # Real reported bug (normal-mode centering, unaffected by the above):
        # with only a trailing fullscreen_btn after the second stretch, the
        # row's two "ends" weren't the same width, so centering _volume_widget
        # between the stretches visibly pulled it off the row's true center
        # (it looked stuck to the left compared to the transport row above,
        # which has no such asymmetry). An invisible spacer matching
        # fullscreen_btn's own width on the LEFT makes both ends symmetric, so
        # the middle (_volume_widget) is genuinely centered regardless of
        # fullscreen_btn's current size — kept in sync by _apply_control_sizes.
        # Unused (left detached) while the fullscreen combined row is active.
        self._volume_row_spacer = QWidget()
        self._volume_row_spacer.setFixedSize(self._SMALL_BTN_SIZE, self._SMALL_BTN_SIZE)

        self._bottom_widget = QWidget()
        self._controls_layout.addWidget(self._bottom_widget)
        self._bottom_fullscreen = False
        self._rebuild_bottom_row()

        self._layout.addWidget(self._controls_widget)

        self._apply_control_sizes(self._ICON_SIZE, self._PLAY_BTN_SIZE, self._SMALL_BTN_SIZE, 0, 100)
        self._set_controls_enabled(False)

    def apply_theme_colors(self, colors) -> None:
        """Called by PreviewPanel.apply_theme_colors() alongside the other
        preview widgets (metadata panel, highlighters, structure tree) so the
        fullscreen button QSS below (which needs real color values, not just
        a QPalette role) stays in sync with a live theme toggle — and so the
        transport AND fullscreen icons' colors do too (see
        _transport_icon_color's own docstring for why play/pause and
        stop/loop resolve to different theme roles; fullscreen shares
        stop/loop's RoundToolButton styling, so it shares their color too)."""
        self._colors = colors
        _refresh_transport_icons(colors, self._player, self._play_pause_btn, self._stop_btn, self._loop_btn)
        self._fullscreen_btn.setIcon(
            preview_icons.get_transport_icon("expand", _transport_icon_color(colors, "expand"))
        )
        self._mute_btn.setIcon(_mute_button_icon(colors, self._audio_output.isMuted()))

    @staticmethod
    def _detach_layout_children(layout) -> None:
        """Pops every item out of `layout` (widgets and nested sub-layouts,
        recursively) and, for any leaf widget found, reparents it to None so
        it survives detached and can be added into a different layout
        afterward. Used by _rebuild_bottom_row() to tear down the row(s)
        below the seek bar in place without losing the shared button/slider
        instances (_transport_widget/_volume_widget/_fullscreen_btn/
        _volume_row_spacer), which are never rebuilt, only re-parented."""
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                continue
            sub = item.layout()
            if sub is not None:
                VideoPreviewWidget._detach_layout_children(sub)

    def _build_normal_bottom_layout(self) -> QVBoxLayout:
        """Embedded-panel arrangement: transport centered on its own row,
        volume+fullscreen centered on a second row below it — comfortable at
        the Preview tab's narrow width, but wastes a whole extra row of
        height once everything is scaled up for fullscreen (see
        _build_fullscreen_bottom_layout)."""
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)
        transport_row = QHBoxLayout()
        transport_row.addStretch(1)
        transport_row.addWidget(self._transport_widget)
        transport_row.addStretch(1)
        col.addLayout(transport_row)
        volume_row = QHBoxLayout()
        volume_row.addWidget(self._volume_row_spacer)
        volume_row.addStretch(1)
        volume_row.addWidget(self._volume_widget)
        volume_row.addStretch(1)
        volume_row.addWidget(self._fullscreen_btn)
        col.addLayout(volume_row)
        return col

    def _build_fullscreen_bottom_layout(self) -> QHBoxLayout:
        """Fullscreen arrangement: ONE row — transport on the left, volume
        and the fullscreen toggle pinned to the right (the conventional
        player layout) — instead of stacking transport and volume+fullscreen
        on two separate rows. Real reported complaint this fixes: "in full-
        screen mode, the volume control takes up a lot of vertical space...
        needs to be moved to the side." _volume_row_spacer (the normal-mode
        centering spacer) is deliberately left out here — there's nothing to
        re-center against once volume sits flush against the row's own
        right edge instead of the middle."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(16)
        row.addWidget(self._transport_widget)
        row.addStretch(1)
        row.addWidget(self._volume_widget)
        row.addWidget(self._fullscreen_btn)
        return row

    def _rebuild_bottom_row(self) -> None:
        """(Re)builds _bottom_widget's layout from the shared transport/
        volume/fullscreen-button widgets, picking the normal or fullscreen
        arrangement per self._bottom_fullscreen. Called once at construction
        and again by _enter_fullscreen()/_exit_fullscreen() whenever that
        flag flips. QWidget only ever allows one layout to be installed at a
        time, so an existing layout must be fully emptied and detached (via
        the QWidget().setLayout(old) idiom — reparents the now-empty layout
        object off _bottom_widget onto a disposable throwaway widget) before
        a fresh one can be set."""
        old = self._bottom_widget.layout()
        if old is not None:
            self._detach_layout_children(old)
            QWidget().setLayout(old)
        new_layout = (
            self._build_fullscreen_bottom_layout() if self._bottom_fullscreen
            else self._build_normal_bottom_layout()
        )
        self._bottom_widget.setLayout(new_layout)

    def _apply_control_sizes(
        self, icon_size: int, play_size: int, small_size: int, time_font_delta: int, volume_max_width: int,
        fullscreen: bool = False,
    ) -> None:
        """Real reported issue: the embedded-panel button sizes (tuned for a
        small Preview-tab pane) looked comically tiny at true fullscreen
        resolution — a thin sliver of barely-visible controls at the bottom of
        a huge picture. Called once at construction with the normal sizes, and
        again by _enter_fullscreen()/_exit_fullscreen() to scale the SAME
        button/label instances up and back down, rather than building a second
        separate set of controls.

        Real bug found via pixel-level rendering tests, in two layers:
        (1) resizing a QSS-styled QToolButton via setFixedSize() alone leaves
        its background stale until the widget is re-polished; (2) once these
        buttons are reparented under the fullscreen window — which has its OWN
        setStyleSheet("background-color: black;") — the app-wide ID-selector
        rules (#AccentRoundButton/#RoundToolButton) stop matching them at all,
        even after unpolish/polish: an ancestor with a local stylesheet breaks
        ID-selector QSS matching for descendants in this Fusion+global-QSS
        setup. (1) alone is fixable with unpolish/polish; (2) is not — the
        only working fix found was giving each button ITS OWN local
        stylesheet (mirroring the exact #AccentRoundButton/#RoundToolButton
        rules from theme.py, with the border-radius recomputed for the new
        size) while inside the fullscreen window, and clearing it back to ""
        on exit so the buttons resume relying on the (here, unbroken) app-wide
        cascade — confirmed via offscreen rendering + pixel sampling that this
        is the only combination that shows the real accent color rather than
        black/transparent in both states."""
        self._loop_btn.setIconSize(QSize(icon_size - 4, icon_size - 4))
        self._loop_btn.setFixedSize(small_size, small_size)
        # Real reported bug: using the same `icon_size` as the small round
        # buttons made the play/pause icon fill a noticeably SMALLER fraction
        # of its own (much bigger, `play_size`) button than loop/stop fill of
        # theirs — barely visible at the embedded panel's sizes, but glaring
        # once fullscreen scales play_size up to 72px against only a 32px
        # icon (a 20px empty margin on every side). Deriving play's icon size
        # from the SAME fill ratio loop/stop already use (icon_size-4 within
        # small_size) keeps every transport button visually consistent
        # regardless of how these sizes get tuned in the future, instead of
        # a second hardcoded magic number.
        play_icon_size = round((icon_size - 4) / small_size * play_size)
        self._play_pause_btn.setIconSize(QSize(play_icon_size, play_icon_size))
        self._play_pause_btn.setFixedSize(play_size, play_size)
        self._stop_btn.setIconSize(QSize(icon_size - 4, icon_size - 4))
        self._stop_btn.setFixedSize(small_size, small_size)
        self._fullscreen_btn.setIconSize(QSize(icon_size - 4, icon_size - 4))
        self._fullscreen_btn.setFixedSize(small_size, small_size)
        self._volume_row_spacer.setFixedSize(small_size, small_size)
        self._mute_btn.setIconSize(QSize(icon_size - 4, icon_size - 4))
        self._volume_slider.setMaximumWidth(volume_max_width)
        time_font = QFont(self._base_time_font)
        time_font.setPointSize(self._base_time_font.pointSize() + time_font_delta)
        self._time_current_label.setFont(time_font)
        self._time_total_label.setFont(time_font)

        c = self._colors
        if fullscreen and c is not None:
            accent_radius = play_size // 2
            self._play_pause_btn.setStyleSheet(
                f"QToolButton {{ background-color: {c.highlight}; border: none; border-radius: {accent_radius}px; }}"
                f"QToolButton:hover {{ background-color: {c.accent_hover}; }}"
                f"QToolButton:pressed {{ background-color: {c.accent_pressed}; }}"
                f"QToolButton:disabled {{ background-color: {c.border}; }}"
            )
            round_radius = small_size // 2
            round_qss = (
                f"QToolButton {{ background-color: {c.button}; border: 1px solid {c.border}; border-radius: {round_radius}px; }}"
                f"QToolButton:hover {{ background-color: {c.surface}; border-color: {c.highlight}; }}"
                f"QToolButton:checked {{ background-color: {c.highlight}; border-color: {c.highlight}; }}"
                f"QToolButton:disabled {{ background-color: transparent; border-color: {c.border}; }}"
            )
            for btn in (self._loop_btn, self._stop_btn, self._fullscreen_btn):
                btn.setStyleSheet(round_qss)
        else:
            for btn in (self._loop_btn, self._play_pause_btn, self._stop_btn, self._fullscreen_btn):
                btn.setStyleSheet("")
                btn.style().unpolish(btn)
                btn.style().polish(btn)
                btn.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        reapply_elided_labels(self._label, self._info_label)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for w in (self._play_pause_btn, self._stop_btn, self._seek_slider, self._loop_btn, self._fullscreen_btn):
            w.setEnabled(enabled)

    def set_video(self, data: bytes, name: str, ext: str, info_text: str = "", autoplay: bool = False) -> None:
        self._exit_fullscreen()
        self._player.stop()
        self._cleanup_temp_file()

        if not data:
            set_elided_label_text(self._label, tr("{name}: видеоданные не найдены", name=name))
            set_elided_label_text(self._info_label, "")
            self._set_controls_enabled(False)
            return

        fd, path = tempfile.mkstemp(suffix=ext or ".mp4")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        self._temp_file = Path(path)

        set_elided_label_text(self._label, name)
        info_parts = [p for p in (ext.lstrip(".").upper() if ext else "", format_size(len(data)), info_text) if p]
        set_elided_label_text(self._info_label, "  ·  ".join(info_parts))
        self._set_controls_enabled(True)
        self._player.setSource(QUrl.fromLocalFile(str(self._temp_file)))
        self._seek_slider.setValue(0)
        self._update_time_label(0, 0)
        if autoplay:
            self._player.play()

    def _toggle_fullscreen(self) -> None:
        if self._fullscreen_window is None:
            self._enter_fullscreen()
        else:
            self._exit_fullscreen()

    def _enter_fullscreen(self) -> None:
        """Moves _video_widget and _controls_widget — as-is, same instances,
        same arrangement, same icons and QSS as the embedded panel — into a
        real top-level fullscreen window, just scaled up via
        _apply_control_sizes(). Deliberately NOT a different look or layout:
        an earlier version rebuilt fullscreen as a separate dark "player
        chrome" with its own icon set and left/right arrangement, which per
        direct feedback looked worse than just enlarging the exact panel
        that already looks right — "it's strange that fullscreen and non-
        fullscreen are different... non-fullscreen looks comfortable"."""
        if self._fullscreen_window is not None:
            return
        win = QWidget(None, Qt.WindowType.Window)
        # ._elided_full_text (set by set_elided_label_text) is the real, un-
        # truncated name — self._label.text() would give the already-elided
        # ("...") display string instead.
        win.setWindowTitle(getattr(self._label, "_elided_full_text", "") or self._label.text() or tr("Видео"))
        win.setStyleSheet("background-color: black;")
        win.installEventFilter(self)  # Escape exits — see eventFilter()
        win_layout = QVBoxLayout(win)
        win_layout.setContentsMargins(0, 0, 0, 0)
        win_layout.setSpacing(0)
        win_layout.addWidget(self._video_widget, 1)

        controls_wrap = QWidget()
        # Same background the embedded panel itself sits on (the app's own
        # theme) — not an invented dark overlay. Real reported bug this
        # avoids: a hardcoded dark bar with the app's native-themed icons
        # (black on some themes) had no guaranteed contrast; reusing the exact
        # backdrop those icons are already confirmed legible against
        # sidesteps the problem entirely instead of needing a whole second
        # icon set to work around it.
        #
        # setAutoFillBackground(True)+setPalette(self.palette()) was tried
        # first (matches the palette-based approach used elsewhere in this
        # app) but confirmed via pixel-sampled offscreen rendering to render
        # fully black/transparent here regardless of unpolish/polish — this
        # window's own setStyleSheet() call above breaks palette-based
        # autoFillBackground painting for a freshly parented child the same
        # way it breaks ID-selector QSS matching (see _apply_control_sizes'
        # docstring). A direct setStyleSheet() on this widget itself sidesteps
        # it — confirmed to render the correct color via the same pixel test.
        controls_wrap.setStyleSheet(f"background-color: {self._colors.surface};")
        wrap_layout = QVBoxLayout(controls_wrap)
        wrap_layout.setContentsMargins(16, 12, 16, 16)
        wrap_layout.addWidget(self._controls_widget)
        win_layout.addWidget(controls_wrap)

        self._fullscreen_window = win
        self._bottom_fullscreen = True
        self._rebuild_bottom_row()
        self._apply_control_sizes(
            icon_size=32, play_size=72, small_size=52, time_font_delta=6, volume_max_width=160, fullscreen=True,
        )
        win.showFullScreen()
        self._fullscreen_btn.setToolTip(tr("Выйти из полноэкранного режима"))

    def _exit_fullscreen(self) -> None:
        if self._fullscreen_window is None:
            return
        self._bottom_fullscreen = False
        self._rebuild_bottom_row()
        self._apply_control_sizes(
            icon_size=self._ICON_SIZE, play_size=self._PLAY_BTN_SIZE, small_size=self._SMALL_BTN_SIZE,
            time_font_delta=0, volume_max_width=100,
        )
        # _video_widget and _controls_widget both left self._layout entirely
        # (added to the fullscreen window's own layout instead) — restore both
        # to their original spots: index 2 for the video (after label/info),
        # then controls_widget appended after it.
        self._layout.insertWidget(2, self._video_widget, 1)
        self._layout.addWidget(self._controls_widget)

        win = self._fullscreen_window
        self._fullscreen_window = None
        win.removeEventFilter(self)
        win.close()
        win.deleteLater()
        self._fullscreen_btn.setToolTip(tr("На весь экран"))

    def eventFilter(self, obj, event) -> bool:
        if (
            self._fullscreen_window is not None and obj is self._fullscreen_window
            and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape
        ):
            self._exit_fullscreen()
            return True
        return super().eventFilter(obj, event)

    def _toggle_mute(self) -> None:
        muted = not self._audio_output.isMuted()
        self._audio_output.setMuted(muted)
        icon = _mute_button_icon(self._colors, muted)
        self._mute_btn.setIcon(icon)
        self._mute_btn.setToolTip(tr("Включить звук") if muted else tr("Выключить звук"))

    def _toggle_play_pause(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _on_loop_toggled(self, checked: bool) -> None:
        # No longer touches self._player.setLoops() at all — see __init__'s
        # comment on why: looping is handled entirely by _on_media_status_changed
        # re-reading this checkbox's state at the moment media actually ends,
        # not by asking the backend to loop internally. The checkbox's own
        # :checked QSS state also swaps its BACKGROUND color — the icon's own
        # color has to follow that switch too, see _transport_icon_color.
        self._loop_btn.setIcon(
            preview_icons.get_transport_icon("loop", _transport_icon_color(self._colors, "loop", checked))
        )

    def _on_media_status_changed(self, status) -> None:
        # See __init__'s comment on self._player.setLoops(Once) — this is now
        # the ONLY place looping happens, not a backstop layered on top of a
        # backend-driven Infinite loop. EndOfMedia always fires here (the
        # backend never auto-loops), so this always sees the loop checkbox's
        # truly current state: checked -> restart from 0, unchecked -> stop.
        if status != QMediaPlayer.MediaStatus.EndOfMedia:
            return
        if self._loop_btn.isChecked():
            self._player.setPosition(0)
            self._player.play()
        else:
            self._player.stop()

    def _on_volume_changed(self, value: int) -> None:
        self._audio_output.setVolume(value / 100.0)

    def _on_state_changed(self, state) -> None:
        is_playing = state == QMediaPlayer.PlaybackState.PlayingState
        icon_kind = "pause" if is_playing else "play"
        self._play_pause_btn.setIcon(preview_icons.get_transport_icon(icon_kind, _transport_icon_color(self._colors, icon_kind)))
        self._play_pause_btn.setToolTip(tr("Пауза") if is_playing else tr("Воспроизвести"))
        if state == QMediaPlayer.PlaybackState.StoppedState and not self._seeking:
            self._seek_slider.setValue(0)
            self._update_time_label(0, self._player.duration())

    def _on_position_changed(self, position_ms: int) -> None:
        if self._seeking:
            return
        self._seek_slider.setValue(position_ms)
        self._update_time_label(position_ms, self._player.duration())

    def _on_duration_changed(self, duration_ms: int) -> None:
        self._seek_slider.setRange(0, duration_ms)
        self._update_time_label(self._player.position(), duration_ms)

    def _on_seek_pressed(self) -> None:
        self._seeking = True

    def _on_seek_moved(self, position_ms: int) -> None:
        self._update_time_label(position_ms, self._player.duration())

    def _on_seek_released(self) -> None:
        self._player.setPosition(self._seek_slider.value())
        self._seeking = False

    @staticmethod
    def _format_ms(ms: int) -> str:
        total_seconds = max(0, ms) // 1000
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}:{seconds:02d}"

    def _update_time_label(self, position_ms: int, duration_ms: int) -> None:
        self._time_current_label.setText(self._format_ms(position_ms))
        self._time_total_label.setText(self._format_ms(duration_ms))

    def _cleanup_temp_file(self) -> None:
        if self._temp_file is not None and self._temp_file.exists():
            try:
                self._temp_file.unlink()
            except OSError:
                pass
        self._temp_file = None

    def stop_playback(self) -> None:
        """Stops playback without touching the loaded source/temp file — same
        "just stop, we might come back shortly" semantics as
        AudioPreviewWidget.stop_playback(), called whenever the selection
        switches to something else so a still-playing video doesn't keep going
        in the background after the Preview tab has moved on. Also exits
        fullscreen — nothing else would, once the underlying source is gone."""
        self._exit_fullscreen()
        self._player.stop()

    def cleanup(self) -> None:
        """Stop playback and remove the temp file — called when the app closes or
        the panel is otherwise torn down."""
        self._exit_fullscreen()
        self._player.stop()
        self._player.setSource(QUrl())
        self._cleanup_temp_file()
