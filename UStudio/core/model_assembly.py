"""A GameObject's meshes assembled into one model, for the 3D preview (stage 2). No Qt.

From the selected GameObject down through its Transform children: each mesh shown by an ENABLED MeshRenderer (its
MeshFilter's mesh) or SkinnedMeshRenderer is placed with the combined local position/rotation/scale of its object
and every parent up to the selected one (which is the origin, so the model is framed around it). Unity's own
hiding is followed: inactive child objects are skipped, and under an LODGroup only LOD 0 is drawn (the other levels
are the same thing, coarser, in the same place). A skinned mesh is placed at its renderer's object in its bind pose
— right for most rigs, approximate for some (no bones are evaluated).

References are resolved among the files already loaded only (object_references._loaded_file): nothing is loaded
from disk. Objects whose TYPE a large load left out (MeshFilter, MeshRenderer...) are read through
SerializedFile.skipped_object() — without it such a model had no parts at all. The result is one MeshGeometry, one part per submesh, so the 3D view draws it unchanged.

Textures (stage 3): each submesh's material (the renderer's m_Materials, by submesh index) gives its main texture
(core.thumbnails' slot order) with the material's tiling/offset. Decoded here, in the preview worker, reduced to
TEXTURE_SIZE; each texture once per model, at most MAX_TEXTURES of them; one over thumbnails.MAX_PIXELS is not
decoded. A part without one keeps its colour.

See-through materials (glass, water, effects): `material_is_transparent` — such parts are drawn half-clear, after
the solid ones, so what is inside them shows (Truck-kun's potion: the red liquid inside its glass)."""

from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from .mesh_geometry import MeshGeometry, MeshNotDrawable, mesh_geometry
from .object_references import _loaded_file

TRANSFORM_CLASSES = (4, 224)            # Transform, RectTransform
_MESH_FILTER, _MESH_RENDERER, _SKINNED_RENDERER, _LOD_GROUP = 33, 23, 137, 205
MAX_OBJECTS = 20000                     # GameObjects walked
MAX_TRIANGLES = 3_000_000               # drawn — past this the rest is left out (and the summary says so)
MAX_TEXTURES = 48                       # different textures decoded per model (the rest of the parts: colour)
WHITE = (1.0, 1.0, 1.0)
# The colour that multiplies each main-texture slot — the one of the SAME pipeline: a material keeps the old
# shader's properties when its shader changes (Truck-kun: a URP material, `_BaseMap`, with a leftover black
# `_Color` — it would draw black). No matching colour: white.
TINT_FOR_SLOT = {
    "_MainTex": ("_Color", "_TintColor"), "_BaseMap": ("_BaseColor",), "_BaseColorMap": ("_BaseColor",),
    "_Albedo": ("_Color",), "_AlbedoMap": ("_Color",), "_FaceTex": ("_FaceColor",),
}


# A render queue above this is Unity's transparent range (2000 = solid, 2450 = cut-out, 3000 = transparent).
_TRANSPARENT_QUEUE = 2500
_QUEUE_NAMES = {"background": 1000, "geometry": 2000, "alphatest": 2450, "transparent": 3000, "overlay": 4000}


def _queue_value(text) -> Optional[int]:
    """A shader's Queue tag ("Transparent", "Geometry+1", "3000") as a number, or None."""
    text = str(text or "").strip().lower().replace(" ", "")
    if text.lstrip("-").isdigit():
        return int(text)
    for name, base in _QUEUE_NAMES.items():
        if text.startswith(name):
            rest = text[len(name):]
            try:
                return base + (int(rest) if rest else 0)
            except ValueError:
                return base
    return None


def _shader_tags(shader) -> dict:
    """The first SubShader's tags of a Shader, keys lower-cased (a bounded read of m_ParsedForm: ~1 ms, never the
    compiled programs). {} when unreadable."""
    try:
        form = (shader.peek_dict(("m_ParsedForm",)) or {}).get("m_ParsedForm") or {}
        subshaders = form.get("m_SubShaders") or []
        tags = ((subshaders[0].get("m_Tags") or {}).get("tags") or []) if subshaders else []
        return {str(k).lower(): v for k, v in tags}
    except Exception:
        return {}


def material_is_transparent(material_data: dict, shader_tags: Optional[dict]) -> bool:
    """Is a material see-through — in Unity's own order of precedence:
    1. its own render queue, when set (m_CustomRenderQueue != -1): above 2500;
    2. its own RenderType tag (stringTagMap): Transparent / not;
    3. its shader's tags (`shader_tags`, from _shader_tags): Queue above 2500, else RenderType Transparent;
    4. the shader is not loaded (None): the material's URP `_Surface` = 1 or Standard `_Mode` 2/3 (Fade/Transparent).
    The material's own `_Surface`/`_Mode` are NOT trusted otherwise: a material keeps the old shader's properties
    when its shader changes (Truck-kun's «lambert16»: `_Mode` 3 left over, queue 2450 = cut-out = solid).
    Survey (Truck-kun, 401 materials, 92 shaders): every one decided by 1-3; the potion glass by its shader's
    Queue tag (custom matcap shader, the material sets nothing)."""
    queue = material_data.get("m_CustomRenderQueue", -1)
    if isinstance(queue, int) and queue != -1:
        return queue > _TRANSPARENT_QUEUE
    render_type = dict(material_data.get("stringTagMap") or []).get("RenderType")
    if render_type:
        return str(render_type).lower() == "transparent"
    if shader_tags is not None:
        shader_queue = _queue_value(shader_tags.get("queue"))
        if shader_queue is not None:
            return shader_queue > _TRANSPARENT_QUEUE
        return str(shader_tags.get("rendertype", "")).lower() == "transparent"
    floats = {k: v for k, v in ((material_data.get("m_SavedProperties") or {}).get("m_Floats") or [])}
    return floats.get("_Surface") == 1 or floats.get("_Mode") in (2, 3)


class _Transparency:
    """material_is_transparent per material, each shader's tags read once per model."""

    def __init__(self):
        self._by_material: Dict[Tuple[int, int], bool] = {}
        self._tags: Dict[Tuple[int, int], dict] = {}

    def of(self, material) -> bool:
        if material is None or getattr(material, "class_id", None) != 21:
            return False
        key = (id(material.assets_file), material.path_id)
        if key not in self._by_material:
            try:
                data = material.parse_as_dict()
                shader = _resolve(material, data.get("m_Shader"))
                if shader is None:          # a large load may have left the Shader type out: read it anyway
                    ptr = data.get("m_Shader") or {}
                    shader_file = _loaded_file(material.assets_file, ptr.get("m_FileID", 0)) if ptr.get(
                        "m_PathID") else None
                    skipped = getattr(shader_file, "skipped_object", None)
                    shader = skipped(ptr["m_PathID"]) if skipped is not None else None
                tags = None
                if shader is not None:
                    skey = (id(shader.assets_file), shader.path_id)
                    if skey not in self._tags:
                        self._tags[skey] = _shader_tags(shader)
                    tags = self._tags[skey]
                self._by_material[key] = material_is_transparent(data, tags)
            except Exception:
                self._by_material[key] = False
        return self._by_material[key]


def material_tint(slot: str, colors: dict) -> tuple:
    """(r, g, b) of the colour that goes with the texture `slot` (`colors`: m_Colors as name -> {r, g, b, a})."""
    for name in TINT_FOR_SLOT.get(slot, ()):
        color = colors.get(name)
        if isinstance(color, dict):
            return tuple(max(0.0, min(1.0, float(color.get(c, 1.0)))) for c in "rgb")
    return WHITE
TEXTURE_SIZE = 512                      # longest side of a texture as drawn in the preview


class NoModel(Exception):
    """Nothing to draw under this GameObject (the preview then shows its fields as before)."""


def _resolve(owner, ptr) -> Optional[object]:
    if not isinstance(ptr, dict):
        return None
    path_id = ptr.get("m_PathID", 0)
    if not path_id:
        return None
    target_file = _loaded_file(owner.assets_file, ptr.get("m_FileID", 0))
    if target_file is None:
        return None
    obj = target_file.objects.get(path_id)
    if obj is None:
        # a type the load left out (a large load skips MeshFilter/MeshRenderer...): read it anyway, read-only — only
        # an edit adopts it into the file (SerializedFile.adopt_skipped), this walk only reads
        skipped = getattr(target_file, "skipped_object", None)
        obj = skipped(path_id) if skipped is not None else None
    return obj


def _vec(d, keys, default) -> List[float]:
    if not isinstance(d, dict):
        return list(default)
    return [float(d.get(k, v)) for k, v in zip(keys, default)]


def local_matrix(transform: dict) -> np.ndarray:
    """4x4 (column vectors) = T * R * S from a Transform's m_LocalPosition / m_LocalRotation / m_LocalScale."""
    tx, ty, tz = _vec(transform.get("m_LocalPosition"), "xyz", (0, 0, 0))
    x, y, z, w = _vec(transform.get("m_LocalRotation"), "xyzw", (0, 0, 0, 1))
    sx, sy, sz = _vec(transform.get("m_LocalScale"), "xyz", (1, 1, 1))
    n = x * x + y * y + z * z + w * w
    if n > 0:
        s = 2.0 / n
        rotation = np.array([
            [1 - s * (y * y + z * z), s * (x * y - z * w), s * (x * z + y * w)],
            [s * (x * y + z * w), 1 - s * (x * x + z * z), s * (y * z - x * w)],
            [s * (x * z - y * w), s * (y * z + x * w), 1 - s * (x * x + y * y)],
        ])
    else:
        rotation = np.eye(3)
    m = np.eye(4)
    m[:3, :3] = rotation * np.array([sx, sy, sz])
    m[:3, 3] = (tx, ty, tz)
    return m


class _Walk:
    def __init__(self, should_cancel: Optional[Callable[[], bool]]):
        self.should_cancel = should_cancel or (lambda: False)
        self.placed: List[Tuple[object, np.ndarray, list]] = []  # (mesh ObjectReader, world matrix, material ptrs)
        self.objects = 0
        self.lod_hidden: set = set()                            # (id(file), path_id) of LOD 1+ renderers

    def visit(self, game_object, world: np.ndarray, is_root: bool) -> None:
        self.objects += 1
        if self.objects > MAX_OBJECTS:
            return
        if self.objects % 200 == 0 and self.should_cancel():
            from .progress import OperationCancelled
            raise OperationCancelled()
        try:
            go = game_object.parse_as_dict()
        except Exception:
            return
        if not is_root and go.get("m_IsActive", True) is False:
            return
        components = []
        for pair in go.get("m_Component") or []:
            comp = _resolve(game_object, pair.get("component") if isinstance(pair, dict) else None)
            if comp is not None:
                components.append(comp)
        by_class: Dict[int, List[object]] = {}
        for comp in components:
            by_class.setdefault(comp.class_id, []).append(comp)

        transform = next((c for cid in TRANSFORM_CLASSES for c in by_class.get(cid, [])), None)
        tdata = {}
        if transform is not None:
            try:
                tdata = transform.parse_as_dict()
            except Exception:
                tdata = {}
        if not is_root:
            world = world @ local_matrix(tdata)

        for lod_group in by_class.get(_LOD_GROUP, []):
            try:
                lods = lod_group.parse_as_dict().get("m_LODs") or []
            except Exception:
                lods = []
            for lod in lods[1:]:
                for entry in lod.get("renderers") or []:
                    renderer = _resolve(lod_group, entry.get("renderer") if isinstance(entry, dict) else None)
                    if renderer is not None:
                        self.lod_hidden.add((id(renderer.assets_file), renderer.path_id))

        self._add_meshes(by_class, world, go.get("m_Name") or "")

        for child_ptr in tdata.get("m_Children") or []:
            child_transform = _resolve(transform, child_ptr)
            if child_transform is None:
                continue
            try:
                child_go = _resolve(child_transform, child_transform.parse_as_dict().get("m_GameObject"))
            except Exception:
                child_go = None
            if child_go is not None:
                self.visit(child_go, world, False)

    def _enabled(self, renderer) -> bool:
        if (id(renderer.assets_file), renderer.path_id) in self.lod_hidden:
            return False
        try:
            return bool(renderer.peek_dict(("m_Enabled",)).get("m_Enabled", True))
        except Exception:
            try:
                return bool(renderer.parse_as_dict().get("m_Enabled", True))
            except Exception:
                return True

    @staticmethod
    def _materials(renderer) -> list:
        """The renderer's materials (resolved ObjectReaders or None), in submesh order."""
        try:
            pointers = renderer.parse_as_dict().get("m_Materials") or []
        except Exception:
            return []
        return [_resolve(renderer, p) for p in pointers]

    def _add_meshes(self, by_class, world, owner: str = "") -> None:
        renderers = [r for r in by_class.get(_MESH_RENDERER, []) if self._enabled(r)]
        if renderers:
            materials = self._materials(renderers[0])
            for mesh_filter in by_class.get(_MESH_FILTER, []):
                try:
                    mesh = _resolve(mesh_filter, mesh_filter.parse_as_dict().get("m_Mesh"))
                except Exception:
                    mesh = None
                if mesh is not None:
                    self.placed.append((mesh, world, materials, owner))
        for skinned in by_class.get(_SKINNED_RENDERER, []):
            if not self._enabled(skinned):
                continue
            try:
                mesh = _resolve(skinned, skinned.parse_as_dict().get("m_Mesh"))
            except Exception:
                mesh = None
            if mesh is not None:
                self.placed.append((mesh, world, self._materials(skinned), owner))


class _Textures:
    """Each material's main texture, decoded once per model (PIL, reduced to TEXTURE_SIZE)."""

    def __init__(self):
        self.images: list = []
        self._by_texture: Dict[Tuple[int, int], int] = {}
        self._by_material: Dict[Tuple[int, int], Tuple[int, tuple]] = {}
        self.texture_of: Dict[Tuple[int, int], Tuple[object, str]] = {}    # material -> (texture, its slot)

    def for_material(self, material) -> Tuple[int, tuple, tuple]:
        """(texture index or -1, (sx, sy, ox, oy), tint (r, g, b))."""
        none = (-1, (1.0, 1.0, 0.0, 0.0), WHITE)
        if material is None or getattr(material, "class_id", None) != 21:
            return none
        key = (id(material.assets_file), material.path_id)
        if key in self._by_material:
            return self._by_material[key]
        result = none
        try:
            result = self._decode(material)
        except Exception:
            result = none
        self._by_material[key] = result
        return result

    def _decode(self, material) -> Tuple[int, tuple, tuple]:
        from .thumbnails import _MAIN_SLOTS, _deref_loaded, _texture_too_big
        saved = material.parse_as_dict().get("m_SavedProperties") or {}
        envs = saved.get("m_TexEnvs") or []
        colors = {e[0]: e[1] for e in saved.get("m_Colors") or []
                  if isinstance(e, (list, tuple)) and len(e) == 2 and isinstance(e[1], dict)}
        slots = {}
        for entry in envs:
            if isinstance(entry, (list, tuple)) and len(entry) == 2 and isinstance(entry[1], dict):
                slots[entry[0]] = entry[1]
        for slot in [s for s in _MAIN_SLOTS if s in slots]:
            env = slots[slot]
            texture = _deref_loaded(env.get("m_Texture"), material)
            if texture is None or texture.class_id != 28:
                continue
            scale, offset = env.get("m_Scale") or {}, env.get("m_Offset") or {}
            uv = (float(scale.get("x", 1)), float(scale.get("y", 1)), float(offset.get("x", 0)),
                  float(offset.get("y", 0)))
            tint = material_tint(slot, colors)
            self.texture_of[(id(material.assets_file), material.path_id)] = (texture, slot)
            tkey = (id(texture.assets_file), texture.path_id)
            if tkey not in self._by_texture:
                if len(self.images) >= MAX_TEXTURES or _texture_too_big(texture):
                    return -1, uv, tint
                image = texture.read().image
                if image is None or not image.width or not image.height:
                    return -1, uv, tint
                image = image.convert("RGBA")
                if max(image.size) > TEXTURE_SIZE:
                    image.thumbnail((TEXTURE_SIZE, TEXTURE_SIZE))
                self._by_texture[tkey] = len(self.images)
                self.images.append(image)
            return self._by_texture[tkey], uv, tint
        return -1, (1.0, 1.0, 0.0, 0.0), WHITE


def gameobject_model(game_object, should_cancel: Optional[Callable[[], bool]] = None) -> MeshGeometry:
    """The assembled model under `game_object`; raises NoModel when it has no visible mesh."""
    walk = _Walk(should_cancel)
    walk.visit(game_object, np.eye(4), True)
    if not walk.placed:
        raise NoModel("no meshes")

    geometries: Dict[Tuple[int, int], Optional[MeshGeometry]] = {}
    positions, normals, uvs, parts, part_texture, part_uv, part_tint = [], [], [], [], [], [], []
    part_transparent: List[bool] = []
    textures = _Textures()
    transparency = _Transparency()
    offset = triangles = meshes = 0
    left_out = 0
    sources: List[tuple] = []
    seen_sources: set = set()

    def note(obj, where: str) -> None:
        key = (id(obj.assets_file), obj.path_id)
        if key not in seen_sources:
            seen_sources.add(key)
            sources.append((obj, where))

    for mesh, world, materials, owner in walk.placed:
        key = (id(mesh.assets_file), mesh.path_id)
        if key not in geometries:
            try:
                geometries[key] = mesh_geometry(mesh.parse_as_object())
            except (MeshNotDrawable, Exception):
                geometries[key] = None
        g = geometries[key]
        if g is None:
            continue
        mesh_triangles = sum(len(s) for s in g.submeshes)
        if triangles + mesh_triangles > MAX_TRIANGLES:
            left_out += 1
            continue
        rot = world[:3, :3]
        positions.append((g.positions.astype(np.float64) @ rot.T + world[:3, 3]).astype(np.float32))
        try:
            normal_matrix = np.linalg.inv(rot).T
        except np.linalg.LinAlgError:
            normal_matrix = rot
        n = g.normals.astype(np.float64) @ normal_matrix.T
        length = np.linalg.norm(n, axis=1, keepdims=True)
        length[length == 0] = 1.0
        normals.append((n / length).astype(np.float32))
        uvs.append(g.uv0 if g.uv0 is not None else np.zeros((g.vertex_count, 2), np.float32))
        mirrored = np.linalg.det(rot) < 0           # a mirrored placement flips the winding
        for index, tris in enumerate(g.submeshes):
            if not len(tris):
                continue
            if mirrored:
                tris = tris[:, ::-1]
            parts.append((tris + offset).astype(np.uint32))
            material = materials[index] if index < len(materials) else (materials[-1] if materials else None)
            texture_index, uv_transform, tint = (textures.for_material(material) if g.uv0 is not None
                                                 else (-1, (1.0, 1.0, 0.0, 0.0), WHITE))
            part_texture.append(texture_index)
            part_uv.append(uv_transform)
            part_tint.append(tint)
            part_transparent.append(transparency.of(material))
            if material is not None:
                note(material, f"{owner or 'GameObject'}: m_Materials[{min(index, len(materials) - 1)}]")
                used = textures.texture_of.get((id(material.assets_file), material.path_id))
                if used is not None:
                    try:
                        material_name = material.peek_name() or "Material"
                    except Exception:
                        material_name = "Material"
                    note(used[0], f"{material_name}: {used[1]}")
        offset += g.vertex_count
        triangles += mesh_triangles
        meshes += 1
    if not parts:
        raise NoModel("no drawable meshes")

    try:
        name = game_object.peek_name() or ""
    except Exception:
        name = ""
    return MeshGeometry(name=name, positions=np.concatenate(positions), normals=np.concatenate(normals),
                        uv0=np.concatenate(uvs), submeshes=parts, part_word="meshes", left_out=left_out,
                        part_count=meshes, textures=textures.images, part_texture=part_texture, part_uv=part_uv,
                        part_tint=part_tint, part_transparent=part_transparent, sources=sources)
