"""Small pictures for the «Сведения» lists (no Qt): a Texture2D, a Sprite (cropped from its atlas), a Material
(its main texture). None when there is nothing to draw or it would cost too much.

Measured on PUSS!'s 801 textures (decode + shrink to 48 px): up to 1024² 3 ms median, 2048² ~73 ms, 4096x2048
~270 ms and ~32 MB while decoding. Textures (and sprite atlases) above MAX_PIXELS are therefore not drawn: the row
keeps its type icon. Nothing here loads a file: a texture is resolved among the loaded files only
(core/object_references._loaded_file), as everywhere in «Сведения».

Sprites: UnityPy's SpriteHelper keeps every fully decoded atlas in the file's `_cache` for the rest of the session
(a 4096² atlas is 64 MB). `AtlasScope` lets a batch of sprite thumbnails share each atlas decode and then removes
exactly the entries the batch added."""

from __future__ import annotations

from typing import Optional

from .object_references import _loaded_file

THUMB_SIZE = 48
MAX_PIXELS = 2048 * 2048
# Material texture slots, most telling first (built-in, URP, TextMeshPro, UI)
_MAIN_SLOTS = ("_MainTex", "_BaseMap", "_BaseColorMap", "_FaceTex", "_AlbedoMap", "_Albedo")


def _shrink(image, size: int):
    """Fit into size x size, keeping the proportions — enlarging too: a 20 px sprite left at its own size was
    unreadable in the list (user report). Enlarged with NEAREST (pixel art stays crisp), reduced with LANCZOS."""
    from PIL import Image
    image = image if image.mode in ("RGBA", "RGB") else image.convert("RGBA")
    width, height = image.size
    if not width or not height:
        return None
    scale = size / max(width, height)
    target = (max(1, round(width * scale)), max(1, round(height * scale)))
    return image.resize(target, Image.Resampling.NEAREST if scale > 1 else Image.Resampling.LANCZOS)


def _deref_loaded(pptr_dict, owner) -> Optional[object]:
    """The loaded object a {'m_FileID', 'm_PathID'} points to, or None (never loads a file)."""
    if not isinstance(pptr_dict, dict) or not pptr_dict.get("m_PathID"):
        return None
    target_file = _loaded_file(owner.assets_file, int(pptr_dict.get("m_FileID", 0) or 0))
    if target_file is None:
        return None
    return target_file.objects.get(int(pptr_dict["m_PathID"]))


def _texture_too_big(texture_obj) -> bool:
    """From the texture's width/height alone (a bounded peek: its image data is not read)."""
    try:
        head = texture_obj.peek_dict(("m_Width", "m_Height")) or {}
        width, height = head.get("m_Width") or 0, head.get("m_Height") or 0
        return not width or not height or width * height > MAX_PIXELS
    except Exception:
        return True


def texture_thumbnail(obj, size: int = THUMB_SIZE):
    if _texture_too_big(obj):
        return None
    return _shrink(obj.read().image, size)


def sprite_thumbnail(obj, size: int = THUMB_SIZE):
    raw = obj.parse_as_dict()
    rd = raw.get("m_RD") or {}
    texture = _deref_loaded(rd.get("texture"), obj)
    if texture is None or texture.type.name != "Texture2D" or _texture_too_big(texture):
        return None
    sprite = obj.read()
    return _shrink(sprite.image, size)


def material_thumbnail(obj, size: int = THUMB_SIZE):
    data = obj.parse_as_dict()
    envs = (data.get("m_SavedProperties") or {}).get("m_TexEnvs") or []
    slots = {}
    for entry in envs:
        if isinstance(entry, (list, tuple)) and len(entry) == 2 and isinstance(entry[1], dict):
            slots[entry[0]] = entry[1].get("m_Texture")
    order = [s for s in _MAIN_SLOTS if s in slots] + [s for s in slots if s not in _MAIN_SLOTS]
    for slot in order:
        texture = _deref_loaded(slots[slot], obj)
        if texture is not None and texture.type.name == "Texture2D":
            return texture_thumbnail(texture, size)
    return None


_MAKERS = {"Texture2D": texture_thumbnail, "Sprite": sprite_thumbnail, "Material": material_thumbnail}
THUMBNAIL_TYPES = frozenset(_MAKERS)


def thumbnail(obj, size: int = THUMB_SIZE):
    """A PIL image no bigger than size x size, or None (no picture, too big, unreadable)."""
    maker = _MAKERS.get(obj.type.name)
    if maker is None:
        return None
    try:
        return maker(obj, size)
    except Exception:
        return None


class AtlasScope:
    """Within the `with` block, sprite thumbnails share UnityPy's decoded-atlas cache; on exit the entries added
    during the block are removed (the cache otherwise keeps every decoded atlas for the whole session)."""

    def __init__(self, objects):
        self._caches = {}
        for obj in objects:
            cache = getattr(getattr(obj, "assets_file", None), "_cache", None)
            if isinstance(cache, dict):
                self._caches[id(cache)] = cache

    def __enter__(self):
        self._before = {key: set(cache.keys()) for key, cache in self._caches.items()}
        return self

    def __exit__(self, *exc):
        for key, cache in self._caches.items():
            for added in set(cache.keys()) - self._before[key]:
                cache.pop(added, None)
        return False


def batch_order(objects: list) -> list:
    """Sprites grouped by atlas so a batch decodes each atlas once (stable otherwise)."""
    def atlas_key(obj):
        if obj.type.name != "Sprite":
            return (0, 0)
        try:
            rd = obj.parse_as_dict().get("m_RD") or {}
            tex = rd.get("texture") or {}
            return (1, (tex.get("m_FileID", 0), tex.get("m_PathID", 0)))
        except Exception:
            return (1, (0, 0))
    return sorted(objects, key=atlas_key)
