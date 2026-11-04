"""A Unity Mesh as numpy arrays — what the 3D preview draws (mesh_view.py) and the model export writes. No Qt.

Everything stays in Unity's own (left-handed) space here; a consumer that needs right-handed coordinates mirrors X
and reverses the triangle winding (as UnityPy's OBJ export does, and mesh_view does on upload)."""

from core.i18n import tr
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np


@dataclass
class MeshGeometry:
    name: str
    positions: np.ndarray                     # (N, 3) float32
    normals: np.ndarray                       # (N, 3) float32 — the mesh's own, or computed (normals_computed)
    uv0: Optional[np.ndarray] = None          # (N, 2) float32
    submeshes: List[np.ndarray] = field(default_factory=list)   # one (M, 3) uint32 triangle array per submesh
    normals_computed: bool = False
    skinned: bool = False                     # has bone weights
    skipped_submeshes: int = 0                # points/lines topology: nothing to shade
    part_word: str = "submeshes"              # what a part is called in the summary ("meshes" for a model)
    left_out: int = 0                         # parts not drawn (an assembled model over its size limit)
    part_count: Optional[int] = None          # parts the summary counts, when not one per submesh (a model: meshes)
    # textures (an assembled model only): PIL images, and per submesh its texture index (-1 = none) and the
    # material's tiling/offset (sx, sy, ox, oy). uv0 then covers every vertex (zeros where a mesh has no UVs).
    textures: List = field(default_factory=list)
    part_texture: List[int] = field(default_factory=list)
    part_uv: List[tuple] = field(default_factory=list)
    part_tint: List[tuple] = field(default_factory=list)   # the material's colour (r, g, b) multiplying its texture
    part_transparent: List[bool] = field(default_factory=list)   # the material is see-through (drawn half-clear)
    # an assembled model: the materials its parts use, each followed by the texture drawn from it, as
    # (ObjectReader, where it comes from) — «Сведения» lists them («Материалы и текстуры»)
    sources: List[tuple] = field(default_factory=list)

    @property
    def vertex_count(self) -> int:
        return len(self.positions)

    @property
    def triangle_count(self) -> int:
        return int(sum(len(s) for s in self.submeshes))

    @property
    def bounds(self):
        """(min xyz, max xyz) over the vertices the triangles use (a mesh may carry unused vertices)."""
        used = self.positions
        if self.submeshes and any(len(s) for s in self.submeshes):
            used = self.positions[np.unique(np.concatenate([s.ravel() for s in self.submeshes if len(s)]))]
        if not len(used):
            zero = np.zeros(3, dtype=np.float32)
            return zero, zero
        return used.min(axis=0), used.max(axis=0)


class MeshNotDrawable(Exception):
    """The mesh has nothing to draw (no vertices / no triangles) — the message says why, for the preview."""


def _array(values, width: int) -> Optional[np.ndarray]:
    if values is None or len(values) == 0:
        return None
    arr = np.asarray(values, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr.reshape(-1, width)
    arr = arr[:, :width]
    return np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)


def computed_normals(positions: np.ndarray, submeshes: List[np.ndarray]) -> np.ndarray:
    """Area-weighted vertex normals (Unity winding: clockwise front faces), for meshes stored without normals."""
    normals = np.zeros_like(positions)
    for tris in submeshes:
        if not len(tris):
            continue
        a, b, c = positions[tris[:, 0]], positions[tris[:, 1]], positions[tris[:, 2]]
        face = np.cross(b - a, c - a)
        for k in range(3):
            np.add.at(normals, tris[:, k], face)
    length = np.linalg.norm(normals, axis=1, keepdims=True)
    length[length == 0] = 1.0
    return (normals / length).astype(np.float32)


def _size(value: float) -> str:
    """A bounds size as a plain number — never scientific notation (user report: «4.6e-05»): 1750, 2.85, 0.004;
    below 0.001 it is «0» (a plane's thickness of 0.00005 is flat for anyone looking)."""
    value = float(value)
    if value >= 100:
        return f"{value:.0f}"
    if value >= 0.001:
        return f"{value:.3g}"
    return "0"


def summary_parts(geometry: "MeshGeometry") -> List[str]:
    """The preview's summary strip, terse English like the other types': vertices, triangles, submeshes (when
    more than one), size x × y × z in the mesh's own units."""
    low, high = geometry.bounds
    parts = geometry.part_count if geometry.part_count is not None else len([s for s in geometry.submeshes if len(s)])
    text = [f"{geometry.vertex_count:,} vertices", f"{geometry.triangle_count:,} triangles"]
    if parts > 1:
        text.append(f"{parts} {geometry.part_word}")
    text.append(" × ".join(_size(v) for v in high - low))
    if geometry.left_out:
        text.append(f"{geometry.left_out} more not shown")
    return text


def mesh_geometry(mesh) -> MeshGeometry:
    """`mesh`: a parsed Mesh object (obj.parse_as_object()). Raises MeshNotDrawable with a plain reason."""
    from UnityPy.helpers.MeshHelper import MeshHandler

    handler = MeshHandler(mesh)
    handler.process()
    name = getattr(mesh, "m_Name", "") or ""
    positions = _array(handler.m_Vertices, 3)
    if positions is None or not len(positions):
        raise MeshNotDrawable(tr("В сетке нет вершин."))
    count = len(positions)

    submeshes: List[np.ndarray] = []
    skipped = 0
    for tris in handler.get_triangles():
        arr = np.asarray(tris, dtype=np.int64).reshape(-1, 3) if len(tris) else np.zeros((0, 3), dtype=np.int64)
        if len(tris) and not all(len(t) == 3 for t in tris[:1]):
            skipped += 1
            continue
        valid = (arr >= 0).all(axis=1) & (arr < count).all(axis=1)
        submeshes.append(arr[valid].astype(np.uint32))
    if not any(len(s) for s in submeshes):
        raise MeshNotDrawable(tr("В сетке нет треугольников.") if not skipped else
                              tr("Сетка состоит только из точек или линий — показывать нечего."))

    normals = _array(handler.m_Normals, 3)
    computed = normals is None or len(normals) != count
    if computed:
        normals = computed_normals(positions, submeshes)
    uv0 = _array(handler.m_UV0, 2)
    if uv0 is not None and len(uv0) != count:
        uv0 = None
    skinned = bool(getattr(handler, "m_BoneWeights", None))
    return MeshGeometry(name=name, positions=positions, normals=normals, uv0=uv0, submeshes=submeshes,
                        normals_computed=computed, skinned=skinned, skipped_submeshes=skipped)
