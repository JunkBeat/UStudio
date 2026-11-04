"""The 3D preview of a Mesh (core/mesh_geometry.py's arrays) — GUI only; the CLI never imports this.

Drawn with Qt's own OpenGL (QOpenGLWidget, GL 2.1 / GLSL 1.20, so old and integrated GPUs work too). Controls: left
drag rotates, right or middle drag pans, the wheel zooms, a double-click resets the view; «Каркас» draws the
triangle edges over the shaded model. Light comes from the viewer and both sides of a face are lit, so a model
looks the same whichever way its faces point. A model with several parts gets one soft shade per part.

Triangles are uploaded non-indexed (3 vertices each, with glDrawArrays) and vertex attributes go through Qt's
setAttributeBuffer: both take plain integers, which avoids PyQt's pointer-or-offset arguments. Unity is left-handed:
X is mirrored and the winding reversed on upload, as UnityPy's OBJ export does. If OpenGL cannot be used, the
widget shows a plain message instead."""

from core.i18n import tr
import math
from typing import Optional

import numpy as np
from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QColor, QImage, QMatrix4x4, QSurfaceFormat, QVector3D, QVector4D
from PyQt6.QtOpenGL import (
    QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram, QOpenGLTexture, QOpenGLVersionFunctionsFactory,
    QOpenGLVersionProfile,
)
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget

_GL_COLOR_BUFFER_BIT = 0x4000
_GL_DEPTH_BUFFER_BIT = 0x0100
_GL_DEPTH_TEST = 0x0B71
_GL_BLEND = 0x0BE2
_GL_SRC_ALPHA = 0x0302
_GL_ONE_MINUS_SRC_ALPHA = 0x0303
_GL_TRIANGLES = 0x0004
_GL_FLOAT = 0x1406
_GL_FRONT_AND_BACK = 0x0408
_GL_LINE = 0x1B01
_GL_FILL = 0x1B02
_GL_POLYGON_OFFSET_FILL = 0x8037
_GL_MULTISAMPLE = 0x809D

_VERTEX_SHADER = """
#version 120
attribute vec3 a_pos;
attribute vec3 a_nrm;
attribute vec2 a_uv;
uniform mat4 u_mvp;
uniform mat3 u_nrm;
varying vec3 v_nrm;
varying vec2 v_uv;
void main() {
    gl_Position = u_mvp * vec4(a_pos, 1.0);
    v_nrm = u_nrm * a_nrm;
    v_uv = a_uv;
}
"""

_FRAGMENT_SHADER = """
#version 120
uniform vec3 u_color;
uniform float u_lit;
uniform float u_textured;
uniform vec4 u_uv;                                // the material's tiling (xy) and offset (zw)
uniform vec3 u_tint;                              // the material's colour
uniform float u_alpha;                            // 1 = solid; a see-through material's part: SEE_THROUGH_ALPHA
uniform sampler2D u_tex;
varying vec3 v_nrm;
varying vec2 v_uv;
void main() {
    vec3 base = u_color;
    float a = u_alpha;
    if (u_textured > 0.5) {
        vec4 t = texture2D(u_tex, v_uv * u_uv.xy + u_uv.zw);
        if (t.a < 0.1) discard;                   // cut-out leaves, fences, decals
        base = t.rgb * u_tint;
        if (u_alpha < 1.0) a = u_alpha * t.a;     // a see-through texture keeps its own fading
    }
    float d = abs(normalize(v_nrm).z);            // headlight, both sides lit
    vec3 c = u_lit > 0.5 ? base * (0.30 + 0.70 * d) : base;
    gl_FragColor = vec4(c, a);
}
"""
_STRIDE = 32                                      # x y z, nx ny nz, u v — float32

_FOV = 40.0     # vertical field of view, degrees
# How opaque a see-through material's part is drawn (glass, water, effects: core.model_assembly
# .material_is_transparent). Not the material's own opacity — the game's shaders differ too much to imitate — just
# enough to show the part AND what is inside or behind it (Truck-kun's potion: the red liquid in its glass).
SEE_THROUGH_ALPHA = 0.35

# soft part colours (a single-part model uses the first: light grey)
_PART_COLORS = [(0.80, 0.80, 0.82), (0.62, 0.74, 0.88), (0.86, 0.72, 0.58), (0.66, 0.84, 0.66),
                (0.84, 0.66, 0.80), (0.86, 0.84, 0.58), (0.60, 0.82, 0.82), (0.78, 0.66, 0.62)]


class _GLView(QOpenGLWidget):
    def __init__(self, on_failed, parent=None):
        super().__init__(parent)
        fmt = QSurfaceFormat()
        fmt.setDepthBufferSize(24)
        fmt.setSamples(4)
        self.setFormat(fmt)
        self.setMinimumSize(120, 120)
        self._on_failed = on_failed
        self._gl = None
        self.initialized = False                # initializeGL ran and succeeded
        self._program: Optional[QOpenGLShaderProgram] = None
        self._buffer: Optional[QOpenGLBuffer] = None
        self._pending = None                    # (vertices (K, 8), parts, center, radius, PIL images)
        self._parts = []                        # (first, count, colour, texture index, (sx, sy, ox, oy), tint)
        self._textures: list = []               # QOpenGLTexture per image
        self.show_textures = True
        self._vertex_count = 0
        self._center = QVector3D(0, 0, 0)
        self._radius = 1.0
        self.wireframe = False
        self._background = QColor("#2b2b2b")
        self._reset_camera()
        self._drag_button = None
        self._last = QPoint()

    # -------------------------------------------------------------- data

    def set_data(self, vertices: np.ndarray, parts, center, radius, images=()) -> None:
        self._pending = (vertices, parts, center, radius, list(images))
        self._center = QVector3D(*center)
        self._radius = max(float(radius), 1e-6)
        self._reset_camera()
        self.update()

    def clear(self) -> None:
        """Frees the GPU copy right away: a hidden widget is not repainted, so waiting for paintGL would keep a big
        mesh (tens of MB) in video memory while another object is shown."""
        self._pending = None
        self._parts = []
        self._vertex_count = 0
        if self.initialized and self._buffer is not None:
            self.makeCurrent()
            self._buffer.bind()
            self._buffer.allocate(0)
            self._buffer.release()
            self._free_textures()
            self.doneCurrent()
        self.update()

    def _free_textures(self) -> None:
        for texture in self._textures:
            texture.destroy()
        self._textures = []

    def set_background(self, color: QColor) -> None:
        self._background = QColor(color)
        self.update()

    def _reset_camera(self) -> None:
        self._yaw = math.radians(-35.0)
        self._pitch = math.radians(20.0)
        self._zoom = 1.0                           # x the distance that fits the model in the view
        self._pan = QVector3D(0, 0, 0)

    def reset_view(self) -> None:
        self._reset_camera()
        self.update()

    # -------------------------------------------------------------- GL

    def initializeGL(self) -> None:
        try:
            profile = QOpenGLVersionProfile()
            profile.setVersion(2, 1)
            self._gl = QOpenGLVersionFunctionsFactory.get(profile, self.context())
            if self._gl is None:
                raise RuntimeError(tr("нет OpenGL 2.1"))
            self._gl.initializeOpenGLFunctions()
            program = QOpenGLShaderProgram(self)
            ok = (program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, _VERTEX_SHADER)
                  and program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, _FRAGMENT_SHADER))
            program.bindAttributeLocation("a_pos", 0)
            program.bindAttributeLocation("a_nrm", 1)
            program.bindAttributeLocation("a_uv", 2)
            if not ok or not program.link():
                raise RuntimeError(program.log().strip() or tr("шейдер не собрался"))
            self._program = program
            self._buffer = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
            self._buffer.create()
            self.initialized = True
        except Exception as e:
            self._gl = None
            self._on_failed(str(e))

    def _upload(self) -> None:
        vertices, parts, _center, _radius, images = self._pending
        self._pending = None
        self._buffer.bind()
        data = np.ascontiguousarray(vertices, dtype=np.float32)
        self._buffer.allocate(data.tobytes(), data.nbytes)
        self._buffer.release()
        self._parts = parts
        self._vertex_count = len(data)
        self._free_textures()
        for image in images:
            self._textures.append(_gl_texture(image))

    def _distance(self) -> float:
        """Camera distance in model radii: the bounding sphere fits the narrower field of view (a tall, narrow
        panel has a narrow horizontal one), with a margin; the wheel scales it."""
        aspect = self.width() / max(1, self.height())
        half_v = math.radians(_FOV / 2)
        half_h = math.atan(math.tan(half_v) * aspect)
        return 1.15 / math.sin(min(half_v, half_h)) * self._zoom

    def _matrices(self):
        aspect = self.width() / max(1, self.height())
        distance = self._distance()
        projection = QMatrix4x4()
        projection.perspective(_FOV, aspect, self._radius * 0.01, self._radius * (distance + 2.0) * 2)
        view = QMatrix4x4()
        view.translate(self._pan.x(), self._pan.y(), -distance * self._radius)
        view.rotate(math.degrees(self._pitch), 1, 0, 0)
        view.rotate(math.degrees(self._yaw), 0, 1, 0)
        view.translate(-self._center)
        return projection, view

    def paintGL(self) -> None:
        gl = self._gl
        if gl is None:
            return
        if self._pending is not None:
            self._upload()
        bg = self._background
        gl.glClearColor(bg.redF(), bg.greenF(), bg.blueF(), 1.0)
        gl.glClear(_GL_COLOR_BUFFER_BIT | _GL_DEPTH_BUFFER_BIT)
        if not self._vertex_count:
            return
        gl.glEnable(_GL_DEPTH_TEST)
        gl.glEnable(_GL_MULTISAMPLE)
        projection, view = self._matrices()
        program = self._program
        program.bind()
        program.setUniformValue("u_mvp", projection * view)
        program.setUniformValue("u_nrm", view.normalMatrix())
        self._buffer.bind()
        for location in (0, 1, 2):
            program.enableAttributeArray(location)
        program.setAttributeBuffer(0, _GL_FLOAT, 0, 3, _STRIDE)
        program.setAttributeBuffer(1, _GL_FLOAT, 12, 3, _STRIDE)
        program.setAttributeBuffer(2, _GL_FLOAT, 24, 2, _STRIDE)
        program.setUniformValue("u_tex", 0)

        gl.glEnable(_GL_POLYGON_OFFSET_FILL)
        gl.glPolygonOffset(1.0, 1.0)              # the wireframe stays visible on top of its own faces
        program.setUniformValue("u_lit", 1.0)
        # Solid parts first; then the see-through ones, blended over them without writing depth (so one does not
        # hide what is behind it). No sorting of the see-through triangles: overlapping glass may blend in the
        # wrong order — invisible at this opacity.
        solid = [part for part in self._parts if not part[6]]
        see_through = [part for part in self._parts if part[6]]
        program.setUniformValue("u_alpha", 1.0)
        self._draw_parts(solid)
        if see_through:
            gl.glEnable(_GL_BLEND)
            gl.glBlendFunc(_GL_SRC_ALPHA, _GL_ONE_MINUS_SRC_ALPHA)
            gl.glDepthMask(False)
            program.setUniformValue("u_alpha", SEE_THROUGH_ALPHA)
            self._draw_parts(see_through)
            gl.glDepthMask(True)
            gl.glDisable(_GL_BLEND)
            program.setUniformValue("u_alpha", 1.0)
        gl.glDisable(_GL_POLYGON_OFFSET_FILL)

        if self.wireframe:
            line = (0.10, 0.10, 0.12) if bg.lightness() > 128 else (0.05, 0.05, 0.07)
            program.setUniformValue("u_textured", 0.0)
            program.setUniformValue("u_lit", 0.0)
            program.setUniformValue("u_color", QVector3D(*line))
            gl.glPolygonMode(_GL_FRONT_AND_BACK, _GL_LINE)
            gl.glDrawArrays(_GL_TRIANGLES, 0, self._vertex_count)
            gl.glPolygonMode(_GL_FRONT_AND_BACK, _GL_FILL)

        for location in (0, 1, 2):
            program.disableAttributeArray(location)
        self._buffer.release()
        program.release()

    def _draw_parts(self, parts) -> None:
        gl, program = self._gl, self._program
        for first, count, color, texture_index, uv, tint, _see_through in parts:
            texture = (self._textures[texture_index]
                       if self.show_textures and 0 <= texture_index < len(self._textures) else None)
            program.setUniformValue("u_color", QVector3D(*color))
            program.setUniformValue("u_textured", 1.0 if texture is not None else 0.0)
            if texture is not None:
                texture.bind(0)
                program.setUniformValue("u_uv", QVector4D(*uv))
                program.setUniformValue("u_tint", QVector3D(*tint))
            gl.glDrawArrays(_GL_TRIANGLES, first, count)
            if texture is not None:
                texture.release(0)

    # -------------------------------------------------------------- mouse

    def mousePressEvent(self, event) -> None:
        self._drag_button = event.button()
        self._last = event.position().toPoint()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_button = None

    def mouseMoveEvent(self, event) -> None:
        if self._drag_button is None:
            return
        pos = event.position().toPoint()
        dx, dy = pos.x() - self._last.x(), pos.y() - self._last.y()
        self._last = pos
        if self._drag_button == Qt.MouseButton.LeftButton:
            self._yaw += dx * 0.01
            self._pitch = max(-1.55, min(1.55, self._pitch + dy * 0.01))
        else:
            # pan: one pixel moves the model by its share of the visible height at the target's distance
            per_pixel = 2 * self._distance() * self._radius * math.tan(math.radians(_FOV / 2)) / max(1, self.height())
            self._pan += QVector3D(dx * per_pixel, -dy * per_pixel, 0)
        self.update()

    def wheelEvent(self, event) -> None:
        """Zooms toward the point under the cursor (user request): the point on the plane through the view's
        target stays under the cursor — the pan moves by what the cursor's offset covers at the old and new
        distance."""
        steps = event.angleDelta().y() / 120.0
        before = self._distance() * self._radius
        self._zoom = max(0.02, min(20.0, self._zoom * (0.85 ** steps)))
        after = self._distance() * self._radius
        pos = event.position()
        ndc_x = 2.0 * pos.x() / max(1, self.width()) - 1.0
        ndc_y = 1.0 - 2.0 * pos.y() / max(1, self.height())
        half = math.tan(math.radians(_FOV / 2))
        aspect = self.width() / max(1, self.height())
        self._pan += QVector3D(ndc_x * half * aspect * (after - before), ndc_y * half * (after - before), 0)
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:
        self.reset_view()


def _gl_texture(image) -> QOpenGLTexture:
    """A PIL image as a GL texture: rows bottom-up (Unity's UV origin is the bottom left, a PIL image starts at
    the top), repeating (UVs outside 0..1 tile, as in Unity), mipmapped."""
    rgba = image.convert("RGBA").transpose(1)               # 1 = FLIP_TOP_BOTTOM
    qimage = QImage(rgba.tobytes(), rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888).copy()
    texture = QOpenGLTexture(QOpenGLTexture.Target.Target2D)
    texture.setData(qimage, QOpenGLTexture.MipMapGeneration.GenerateMipMaps)
    texture.setWrapMode(QOpenGLTexture.WrapMode.Repeat)
    texture.setMinMagFilters(QOpenGLTexture.Filter.LinearMipMapLinear, QOpenGLTexture.Filter.Linear)
    return texture


def _gl_vertices(geometry):
    """Non-indexed, right-handed triangles: (K, 8) float32 [x y z nx ny nz u v], the parts' (first, count, colour,
    texture index, uv tiling/offset, tint, see-through), the centre and the radius of the bounds (in the mirrored
    space)."""
    positions = geometry.positions.copy()
    normals = geometry.normals.copy()
    positions[:, 0] *= -1
    normals[:, 0] *= -1
    uv = geometry.uv0 if geometry.uv0 is not None else np.zeros((len(positions), 2), dtype=np.float32)
    part_texture = list(getattr(geometry, "part_texture", []) or [])
    part_uv = list(getattr(geometry, "part_uv", []) or [])
    part_tint = list(getattr(geometry, "part_tint", []) or [])
    part_transparent = list(getattr(geometry, "part_transparent", []) or [])
    chunks, parts, first = [], [], 0
    numbered = [(i, s) for i, s in enumerate(geometry.submeshes) if len(s)]
    for n, (i, tris) in enumerate(numbered):
        order = tris[:, ::-1].ravel()                       # reversed winding after mirroring X
        chunk = np.empty((len(order), 8), dtype=np.float32)
        chunk[:, :3] = positions[order]
        chunk[:, 3:6] = normals[order]
        chunk[:, 6:] = uv[order]
        chunks.append(chunk)
        color = _PART_COLORS[0] if len(numbered) == 1 else _PART_COLORS[n % len(_PART_COLORS)]
        texture_index = part_texture[i] if i < len(part_texture) else -1
        uv_transform = part_uv[i] if i < len(part_uv) else (1.0, 1.0, 0.0, 0.0)
        tint = part_tint[i] if i < len(part_tint) else (1.0, 1.0, 1.0)
        see_through = bool(part_transparent[i]) if i < len(part_transparent) else False
        parts.append((first, len(order), color, texture_index, uv_transform, tint, see_through))
        first += len(order)
    vertices = np.concatenate(chunks) if chunks else np.zeros((0, 8), dtype=np.float32)
    low, high = geometry.bounds
    low, high = low.copy(), high.copy()
    low[0], high[0] = -high[0], -low[0]
    center = (low + high) / 2
    radius = float(np.linalg.norm(high - low) / 2) or 1.0
    return vertices, parts, tuple(float(v) for v in center), radius


class MeshView(QWidget):
    """The preview page: a toolbar row («Каркас», «Текстуры» when the model has any) over the GL view. The mesh's facts (vertices, triangles,
    submeshes, size) are in the summary strip under the preview (core.mesh_geometry.summary_parts)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 0)
        self.chk_wireframe = QCheckBox(tr("Каркас"))
        self.chk_wireframe.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.chk_wireframe.toggled.connect(self._on_wireframe)
        bar.addWidget(self.chk_wireframe)
        self.chk_textures = QCheckBox(tr("Текстуры"))           # shown only for a model that has textures
        self.chk_textures.setChecked(True)
        self.chk_textures.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.chk_textures.toggled.connect(self._on_textures)
        self.chk_textures.hide()
        bar.addWidget(self.chk_textures)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.stack = QStackedWidget()
        self.gl = _GLView(self._on_gl_failed)
        self.failed = QLabel()
        self.failed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.failed.setWordWrap(True)
        self.stack.addWidget(self.gl)
        self.stack.addWidget(self.failed)
        layout.addWidget(self.stack, 1)

    def set_geometry(self, geometry) -> None:
        vertices, parts, center, radius = _gl_vertices(geometry)
        images = list(getattr(geometry, "textures", []) or [])
        self.gl.set_data(vertices, parts, center, radius, images)
        self.chk_textures.setVisible(bool(images))
        # Where no OpenGL context can be made at all, Qt never calls initializeGL and the area just stays empty:
        # say so instead (checked once the view has had time to come up).
        QTimer.singleShot(1500, self._check_context)

    def _check_context(self) -> None:
        if self.gl.isVisible() and not self.gl.initialized and self.stack.currentWidget() is self.gl:
            self._on_gl_failed(tr("не удалось включить OpenGL"))

    def clear(self) -> None:
        self.gl.clear()

    def apply_theme_colors(self, colors) -> None:
        self.gl.set_background(QColor(colors.base))

    def _on_textures(self, on: bool) -> None:
        self.gl.show_textures = on
        self.gl.update()

    def _on_wireframe(self, on: bool) -> None:
        self.gl.wireframe = on
        self.gl.update()

    def _on_gl_failed(self, reason: str) -> None:
        self.failed.setText(tr("3D-просмотр недоступен на этом компьютере: {reason}", reason=reason))
        self.stack.setCurrentWidget(self.failed)
