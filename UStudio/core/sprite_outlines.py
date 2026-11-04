"""Which parts of a texture its sprites take their pictures from — the texture preview's «Контуры спрайтов» (no Qt).

The sprites of a texture are found from the objects that point at it (the «Используется в» index, or a scan of the
texture's own file when there is no index):
- a Sprite whose `m_RD.texture` is this texture: its rectangle is `m_RD.textureRect` (what UnityPy's SpriteHelper
  crops; equal to `m_Rect` for an unpacked sprite);
- a SpriteAtlas (Unity 2017+ packing) whose `m_RenderDataMap` entries point at it: each entry's `textureRect`, the
  sprite being the packed one whose `m_RenderDataKey` equals the entry's key (Lego Party's carousel atlas: the
  sprites live in another bundle). A sprite whose file is not loaded is still outlined, without a name.
A sprite found both ways is listed once (the atlas entry wins, as in SpriteHelper).

Rectangles are returned in IMAGE coordinates (origin top-left, as Texture2D.image shows the texture): Unity's are
bottom-left, so top = texture height - y - height. Rectangles only (no tight mesh outline). Nothing here loads a
file: references are resolved among the loaded files only (object_references._loaded_file)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from .object_references import _loaded_file

SOURCE_TYPES = frozenset({"Sprite", "SpriteAtlas"})
# A texture with more sprites than this is outlined up to here (a font atlas of thousands of glyph sprites would
# only be a grid of lines anyway).
MAX_OUTLINES = 5000


@dataclass
class SpriteOutline:
    name: str              # the sprite's name ("" when its file is not loaded)
    x: float               # image coordinates: left/top edge, in texture pixels
    y: float
    width: float
    height: float
    sprite: object = None  # the Sprite's ObjectReader, or None (not loaded)


def _target(pptr, owner):
    """The loaded object a {'m_FileID', 'm_PathID'} dict points to, or None (never loads a file)."""
    if not isinstance(pptr, dict) or not pptr.get("m_PathID"):
        return None
    target_file = _loaded_file(owner.assets_file, int(pptr.get("m_FileID", 0) or 0))
    if target_file is None:
        return None
    return target_file.objects.get(int(pptr["m_PathID"]))


def _points_at(pptr, owner, texture) -> bool:
    target = _target(pptr, owner)
    return target is texture or (target is not None and target.path_id == texture.path_id
                                 and target.assets_file is texture.assets_file)


def _key(render_data_key):
    """A hashable form of m_RenderDataKey / an m_RenderDataMap key: (GUID dict, int)."""
    try:
        guid, second = render_data_key
        if isinstance(guid, dict):
            guid = tuple(guid[k] for k in sorted(guid))
        return (guid, int(second))
    except Exception:
        return None


def _rect(rect: dict):
    try:
        x, y, w, h = (float(rect[k]) for k in ("x", "y", "width", "height"))
    except Exception:
        return None
    return (x, y, w, h) if w > 0 and h > 0 else None


def _ident(obj):
    return (id(obj.assets_file), obj.path_id)


def candidate_sources(texture, usage_users=None) -> list:
    """The objects that may hold sprites of `texture`: from the usage index's users of it when given (a list of
    (source, field)), else every Sprite/SpriteAtlas of the texture's own file (no reads, a type check only)."""
    if usage_users is not None:
        seen, out = set(), []
        for source, _field in usage_users:
            try:
                if source.type.name in SOURCE_TYPES and _ident(source) not in seen:
                    seen.add(_ident(source))
                    out.append(source)
            except Exception:
                continue
        return out
    out = []
    for obj in list(getattr(texture.assets_file, "objects", {}).values()):
        try:
            if obj.type.name in SOURCE_TYPES:
                out.append(obj)
        except Exception:
            continue
    return out


def sprite_outlines(texture, sources: list, should_cancel: Optional[Callable[[], bool]] = None) -> List[SpriteOutline]:
    """The rectangles of `texture` its sprites use, in image coordinates, sorted by name. `sources` from
    candidate_sources(). Unreadable sources are skipped."""
    should_cancel = should_cancel or (lambda: False)
    try:
        height = float((texture.peek_dict(("m_Height",)) or {}).get("m_Height") or 0)
    except Exception:
        height = 0.0
    found: dict = {}            # sprite identity (or a stand-in for an unloaded one) -> (name, unity rect, sprite)
    atlas_done: set = set()     # sprites already given their rectangle by an atlas

    atlases = [s for s in sources if s.type.name == "SpriteAtlas"]
    sprites = [s for s in sources if s.type.name == "Sprite"]
    for atlas in atlases:
        if should_cancel():
            return []
        try:
            data = atlas.peek_dict(("m_PackedSprites", "m_PackedSpriteNamesToIndex", "m_RenderDataMap")) or {}
        except Exception:
            continue
        entries = {}
        for entry in data.get("m_RenderDataMap") or []:
            try:
                key, render = entry
            except Exception:
                continue
            if isinstance(render, dict) and _points_at(render.get("texture"), atlas, texture):
                rect, k = _rect(render.get("textureRect") or {}), _key(key)
                if rect is not None and k is not None:
                    entries[k] = rect
        if not entries:
            continue
        names = data.get("m_PackedSpriteNamesToIndex") or []
        matched = set()
        for i, pptr in enumerate(data.get("m_PackedSprites") or []):
            sprite = _target(pptr, atlas)
            if sprite is None:
                continue
            try:
                head = sprite.peek_dict(("m_Name", "m_RenderDataKey")) or {}
            except Exception:
                continue
            k = _key(head.get("m_RenderDataKey"))
            if k in entries and k not in matched:
                matched.add(k)
                name = head.get("m_Name") or (names[i] if i < len(names) else "")
                found[_ident(sprite)] = (name, entries[k], sprite)
                atlas_done.add(_ident(sprite))
        for k, rect in entries.items():          # packed sprites whose file is not loaded
            if k not in matched:
                found[("atlas", _ident(atlas), k)] = ("", rect, None)

    for i, sprite in enumerate(sprites):
        if i % 64 == 0 and should_cancel():
            return []
        if _ident(sprite) in atlas_done:
            continue
        try:
            head = sprite.peek_dict(("m_Name", "m_Rect", "m_RD")) or {}
        except Exception:
            continue
        rd = head.get("m_RD") or {}
        if not _points_at(rd.get("texture"), sprite, texture):
            continue
        rect = _rect(rd.get("textureRect") or {}) or _rect(head.get("m_Rect") or {})
        if rect is not None:
            found[_ident(sprite)] = (head.get("m_Name") or "", rect, sprite)

    outlines = []
    for name, (x, y, w, h), sprite in found.values():
        top = height - y - h if height else y
        outlines.append(SpriteOutline(name=name, x=x, y=top, width=w, height=h, sprite=sprite))
    outlines.sort(key=lambda o: (o.name == "", o.name.lower(), o.y, o.x))
    return outlines[:MAX_OUTLINES]
