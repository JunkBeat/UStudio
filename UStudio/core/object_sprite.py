"""Sprite -> source texture navigation and sprite import (paste into the atlas, re-encode)."""

from core.i18n import current_language, tr
import traceback
from typing import Optional

from .object_common import IMPORT_WARNING_PREFIX, _FULL_MIPMAP_CHAIN, _TEXTURE_QUALITY_TO_ENCODER


def _resolve_sprite_render_data(data):
    """Returns the SpriteRenderData actually in effect for this sprite — its own
    m_RD, UNLESS the sprite is packed into a SpriteAtlas (Unity 2017+'s newer
    sprite-packing system), in which case the real texture/rect live in the
    atlas's own m_RenderDataMap instead and m_RD can be empty or point at an
    unpacked placeholder. Mirrors UnityPy's own
    export.SpriteHelper.get_image_from_sprite()'s atlas-lookup logic exactly
    (not reusable directly — that function returns the final cropped PIL image,
    not this intermediate render-data record) — needed here too since, before
    this fix, resolve_sprite_texture()/build_sprite_region_image() read m_RD
    unconditionally and so silently got the wrong (or no) texture for any
    atlas-packed sprite, even though the sprite's own (correctly atlas-aware)
    cropped preview already worked fine."""
    from UnityPy.classes import SpriteAtlasData
    from UnityPy.enums import ClassIDType

    atlas = None
    if data.m_SpriteAtlas:
        atlas = data.m_SpriteAtlas.deref_parse_as_object()
    elif data.m_AtlasTags:
        for obj in data.assets_file.objects.values():
            if obj.type == ClassIDType.SpriteAtlas and obj.peek_name() == data.m_AtlasTags[0]:
                atlas = obj.parse_as_object()
                break

    if atlas:
        render_data = next((v for k, v in atlas.m_RenderDataMap if k == data.m_RenderDataKey), None)
        if isinstance(render_data, SpriteAtlasData):
            return render_data
    return data.m_RD


def resolve_sprite_texture(obj):
    """Returns the Texture2D ObjectReader a Sprite's pixels actually come from —
    atlas-aware (see _resolve_sprite_render_data()), so this also works for a
    sprite packed into a SpriteAtlas, not just a loose/unpacked one. Raises on
    failure — callers decide how to report it (this mirrors export_object()'s
    per-branch try/except style rather than swallowing errors itself, since a
    caller may want to show the user why the jump failed)."""
    data = obj.parse_as_object()
    render_data = _resolve_sprite_render_data(data)
    texture_obj = render_data.texture.deref()
    if texture_obj is None:
        raise ValueError(tr("Ссылка на текстуру пуста или не может быть разрешена."))
    return texture_obj


def build_sprite_region_image(obj):
    """Returns a PIL Image of the sprite's FULL source texture (same orientation
    as Texture2D.image, i.e. what the texture's own Preview tab shows) with the
    sprite's region outlined in red — "where do this sprite's pixels come from".

    textureRect is in Unity's native bottom-left-origin pixel space (the same
    space SpriteHelper.get_image_from_sprite crops against BEFORE its own final
    flip — confirmed by reading that function directly: it calls
    get_image_from_texture2d(..., flip=False) and crops with textureRect's raw
    x/y, only flipping the already-cropped result at the very end). Texture2D.image
    uses flip=True (its default) instead — display-oriented, top-left-origin — so
    the rect's y has to be converted: top = image_height - y - height."""
    data = obj.parse_as_object()
    render_data = _resolve_sprite_render_data(data)
    rect = render_data.textureRect
    texture_obj = render_data.texture.deref()
    if texture_obj is None:
        raise ValueError(tr("Ссылка на текстуру пуста или не может быть разрешена."))
    tex_data = texture_obj.parse_as_object()
    # RGBA, not RGB: a real reported bug — a transparent source PNG rendered as a
    # solid white (or, for some texture formats, a seemingly "random" garbage)
    # rectangle here. .convert("RGB") was throwing away the alpha channel, so
    # whatever RGB bytes happened to be stored under a fully-transparent pixel
    # (exporters routinely leave that unspecified/arbitrary, since it's normally
    # invisible) got shown as if it were opaque real color. The normal Texture2D/
    # Sprite preview never had this bug because it never drops alpha — it relies
    # on ImagePreviewWidget's own checkerboard background to show transparency,
    # same as this should.
    img = tex_data.image.convert("RGBA")

    x, y, w, h = rect.x, rect.y, rect.width, rect.height
    top = img.height - y - h
    box = (x, top, x + w, top + h)

    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    outline_width = max(2, min(img.width, img.height) // 250)
    draw.rectangle(box, outline="red", width=outline_width)
    return img, texture_obj


# Packing-rotation transpose Unity applies when EXPORTING a packed sprite's
# pixels to their final displayed orientation (SpriteHelper.get_image_from_
# sprite's own transpose calls, read directly from that source — not
# guessed). Confirmed empirically, not derived by hand: cropping the box
# above out of Texture2D.image (flip=True, top-left-origin — the SAME
# orientation build_sprite_region_image already uses) and then applying THIS
# SAME transpose reproduces get_image_from_sprite()'s real output exactly,
# for every rotation case including Rotate90 (verified via a synthetic
# uniquely-addressable test texture, byte-for-byte, before trusting this for
# anything real — the naive symbolic derivation for Rotate90 specifically
# does NOT commute the way the other three self-inverse cases do, which is
# exactly why this was tested instead of assumed).
_SPRITE_PACKING_DISPLAY_TRANSPOSE = {
    "kSPRNone": None,
    "kSPRFlipHorizontal": "FLIP_LEFT_RIGHT",
    "kSPRFlipVertical": "FLIP_TOP_BOTTOM",
    "kSPRRotate180": "ROTATE_180",
    "kSPRRotate90": "ROTATE_90",
}


# The INVERSE of each of the above — self-inverse for the first four
# (applying the identical transpose again undoes it), but Rotate90's own
# inverse is Rotate270 (90+270=360), NOT itself — confirmed by the same test.
_SPRITE_PACKING_INVERSE_TRANSPOSE = {
    "kSPRNone": None,
    "kSPRFlipHorizontal": "FLIP_LEFT_RIGHT",
    "kSPRFlipVertical": "FLIP_TOP_BOTTOM",
    "kSPRRotate180": "ROTATE_180",
    "kSPRRotate90": "ROTATE_270",
}


def import_sprite_converted(obj, file_path, *, texture_quality: str = "high") -> Optional[str]:
    """PNG -> a rectangular region of the sprite's own source Texture2D
    (atlas-aware — see _resolve_sprite_render_data). No prior art existed for
    this anywhere (even the reference implementation this project looked at
    for the whole converted-import initiative has Sprite.import_() raising
    NotImplementedError) — this is a fresh design, researched and empirically
    verified before writing, not adapted from existing code.

    Deliberately does NOT attempt block-level surgical patching of the
    atlas's own compressed bytes (BC/ETC/ASTC are block-based, 4x4 or larger,
    and a real atlas rect is not guaranteed block-aligned — corrupting every
    block straddling the region's edges is the exact risk ROADMAP.md flagged
    for this phase). Instead: decode the ENTIRE atlas texture, paste the new
    region in, and re-encode the WHOLE texture through the already-verified
    Phase 1 pipeline (Texture2D.set_image()). This can never corrupt a block
    boundary — nothing here touches compressed bytes directly — at a real,
    accepted cost: every OTHER sprite packed into the same atlas texture also
    gets silently decoded and recompressed, costing it a little quality on a
    lossy format (BC7 "best" already measured very close to lossless
    elsewhere in this project, so likely imperceptible, but real and worth
    surfacing to the user rather than hiding).

    A sprite with its own render data (not on an atlas, not packed) goes
    through _import_unpacked_sprite() — any size, mesh made rectangular.

    Scope for packed/atlas sprites: only simple-rect and flip/rotate-packed sprites. A sprite
    packed with Unity's "Tight" mode AND a real per-triangle UV mesh
    (SpriteHelper.render_sprite_mesh's own case — confirmed by reading that
    function: it only fires when `mesh.m_UV0` has actual non-zero data, the
    exact same condition checked here) is refused with a clear message
    instead of guessed at — reversing a per-triangle affine UV remap has no
    existing reference to verify against anywhere, exactly the class of
    unverified binary-format risk this project's own methodology avoids."""
    from PIL import Image as PILImage
    from PIL.Image import Transpose

    from UnityPy.export.SpriteHelper import SpriteSettings

    try:
        data = obj.parse_as_object()
    except Exception as e:
        return tr("Не удалось прочитать текущие данные объекта: {error}\n{format_exc}", error=e, format_exc=traceback.format_exc())

    try:
        render_data = _resolve_sprite_render_data(data)
        texture_obj = render_data.texture.deref()
    except Exception as e:
        return tr("Не удалось определить исходную текстуру спрайта: {error}", error=e)
    if texture_obj is None:
        return tr("Ссылка на текстуру пуста или не может быть разрешена — импорт спрайта невозможен.")

    settings = SpriteSettings(render_data.settingsRaw)
    rotation_name = settings.packingRotation.name if settings.packed else "kSPRNone"

    if settings.packed and settings.packingMode.name == "kSPMTight":
        # Mirrors SpriteHelper.get_image_from_sprite's own exact branch
        # condition (mesh.m_UV0 with real data -> per-triangle remap; empty/
        # all-zero UV0 -> just a polygon alpha mask over the plain rect,
        # which a full-rect replacement handles fine without special-casing).
        try:
            from UnityPy.helpers.MeshHelper import MeshHandler
            mesh = MeshHandler(data.m_RD, obj.version)
            mesh.process()
            has_mesh_uv = bool(mesh.m_UV0) and any(u or v for u, v in mesh.m_UV0)
        except Exception:
            has_mesh_uv = False
        if has_mesh_uv:
            return (
                tr("Импорт недоступен: у этого спрайта задана нестандартная сетка (tight packing с собственной "
                   "UV-разметкой) — его пиксели растянуты по треугольникам, а не просто вырезаны прямоугольником, и "
                   "надёжного способа выполнить обратное преобразование нет. Используйте Raw-импорт или "
                   "отредактируйте текстуру атласа вручную.")
            )

    try:
        img = PILImage.open(file_path)
        img.load()
    except Exception as e:
        return tr("Не удалось открыть файл изображения: {error}", error=e)

    if not settings.packed and render_data is data.m_RD and not _on_atlas(data):
        return _import_unpacked_sprite(obj, img, texture_obj, texture_quality)

    box = _pixel_box(render_data.textureRect)
    display_width, display_height = box[2], box[3]
    if rotation_name == "kSPRRotate90":
        display_width, display_height = box[3], box[2]

    if img.width != display_width or img.height != display_height:
        return (
            tr("Размер изображения {width}x{height} не совпадает с ожидаемым для этого спрайта — "
               "{display_width}x{display_height}. Спрайт в атласе можно заменить только картинкой того же "
               "размера.", width=img.width, height=img.height, display_width=display_width, display_height=display_height)
        )

    region = img.convert("RGBA")
    inverse_name = _SPRITE_PACKING_INVERSE_TRANSPOSE.get(rotation_name)
    if inverse_name is not None:
        region = region.transpose(getattr(Transpose, inverse_name))

    try:
        tex_data = texture_obj.parse_as_object()
        full_img = tex_data.image.convert("RGBA")
    except Exception as e:
        return tr("Не удалось декодировать текущую текстуру атласа: {error}\n{format_exc}", error=e, format_exc=traceback.format_exc())

    full_img.paste(region, (box[0], full_img.height - box[1] - box[3]))

    error = _store_texture(tex_data, full_img, texture_quality)
    if error:
        return error
    _forget_decoded_texture(obj, render_data.texture.path_id)

    if settings.packed:
        return (
            IMPORT_WARNING_PREFIX + tr("спрайт импортирован, но текстура атласа пересобрана целиком — другие "
                                       "спрайты в этом же атласе могли немного потерять в качестве при повторном сжатии.")
        )
    return None


def _on_atlas(data) -> bool:
    atlas = getattr(data, "m_SpriteAtlas", None)
    return bool((atlas is not None and atlas.path_id) or getattr(data, "m_AtlasTags", None))


def _pixel_box(rect):
    """A (possibly fractional) Unity rect — a dict or an object — as whole pixels (x, y, width, height),
    rounded edge by edge: the same rounding PIL's crop() applies when the sprite is exported, so an exported
    picture fits back."""
    get = rect.get if isinstance(rect, dict) else (lambda k: getattr(rect, k))
    x, y, w, h = get("x"), get("y"), get("width"), get("height")
    x0, y0, x1, y1 = round(x), round(y), round(x + w), round(y + h)
    return (int(x0), int(y0), int(x1 - x0), int(y1 - y0))


def _store_texture(tex_data, full_img, texture_quality: str) -> Optional[str]:
    """Re-encodes the whole texture with `full_img` and saves it, keeping the texture's mip state."""
    encoder_quality = _TEXTURE_QUALITY_TO_ENCODER.get(texture_quality, "best")
    # Preserve whatever mip state the atlas already had — forcing
    # mipmap_count=1 unconditionally would silently drop existing mips for
    # any atlas that actually uses them.
    # m_MipMap only exists in old schemas (it is None from Unity 5.2 on, where
    # m_MipCount replaced it), so m_MipCount is the primary signal and its
    # exact value is kept (an atlas may have a truncated chain).
    existing_mips = getattr(tex_data, "m_MipCount", None) or 0
    if existing_mips > 1:
        mip_count = existing_mips
    else:
        mip_count = _FULL_MIPMAP_CHAIN if getattr(tex_data, "m_MipMap", False) else 1
    try:
        tex_data.set_image(full_img, mipmap_count=mip_count, quality=encoder_quality)
        tex_data.save()
    except Exception as e:
        return tr("Не удалось пересобрать текстуру атласа: {error}\n{format_exc}", error=e, format_exc=traceback.format_exc())
    return None


def _forget_decoded_texture(obj, texture_path_id) -> None:
    """Real bug caught via an actual round-trip test, not assumed: UnityPy's
    own SpriteHelper.get_image() caches the FULLY DECODED atlas image on
    obj.assets_file._cache, keyed by the texture's path_id (or a
    (texture_path_id, alpha_texture_path_id) tuple when an alpha texture is
    involved). Without clearing it, re-previewing THIS sprite (or any OTHER
    sprite sharing the same atlas texture) in the same session would keep
    showing the pre-edit image. Removing every matching cache entry (plain or
    tuple-keyed) forces the next read to decode fresh."""
    try:
        cache = obj.assets_file._cache
        for key in list(cache.keys()):
            if key == texture_path_id or (isinstance(key, tuple) and key and key[0] == texture_path_id):
                del cache[key]
    except Exception:
        pass


def _others_on_texture(obj, texture_obj) -> bool:
    """Another sprite (or an atlas) takes pixels from this texture — among the loaded sprites of the texture's
    file and of this sprite's file (the same reach as the texture preview's «Контуры спрайтов» without the
    usage index). An unreadable answer counts as "yes"."""
    from .sprite_outlines import candidate_sources, sprite_outlines

    try:
        sources = candidate_sources(texture_obj)
        if obj.assets_file is not texture_obj.assets_file:
            seen = {id(s) for s in sources}
            for other in list(obj.assets_file.objects.values()):
                if other.type.name in ("Sprite", "SpriteAtlas") and id(other) not in seen:
                    sources.append(other)
        me = (id(obj.assets_file), obj.path_id)
        for outline in sprite_outlines(texture_obj, sources):
            sprite = outline.sprite
            if sprite is None or (id(sprite.assets_file), sprite.path_id) != me:
                return True
        return False
    except Exception:
        return True


def _size_text(w, h) -> str:
    return f"{w}x{h}"


def _import_unpacked_sprite(obj, img, texture_obj, texture_quality: str) -> Optional[str]:
    """A sprite with its own render data (not on an atlas, not packed). The picture may be:

    - the size of the sprite's whole rectangle (m_Rect), or of its trimmed part (`textureRect` rounded — what
      the export writes for a «Tight» sprite: Unity trims it to its alpha, a FRACTIONAL box, so comparing the
      picture with it exactly refused every such sprite); it goes into that box, and the mesh becomes a
      rectangle over the box (core.sprite_mesh) — a «Tight» mesh follows the OLD picture's outline and would
      clip the new one in game;
    - any other size, when the sprite is alone on a texture it fills whole: the texture takes the picture's
      size, and the sprite's scale (pixels per unit), borders, offset and physics outline are recomputed so
      the sprite keeps its on-screen size along the axis that grew least (a 2x sharper picture looks the
      same; a wider one gets wider).
    Returns None, a warning (IMPORT_WARNING_PREFIX) or an error."""
    from . import sprite_mesh

    try:
        tree = obj.read_typetree()
        tex_data = texture_obj.parse_as_object()
        tex_w, tex_h = int(tex_data.m_Width), int(tex_data.m_Height)
    except Exception as e:
        return tr("Не удалось прочитать спрайт или его текстуру: {error}\n{format_exc}", error=e, format_exc=traceback.format_exc())

    rect_box = _pixel_box(tree["m_Rect"])
    trimmed_box = _pixel_box(tree["m_RD"]["textureRect"])
    size = (img.width, img.height)
    problem = sprite_mesh.full_rect_problem(tree, obj.version)
    note = None
    resized = False

    if size == rect_box[2:]:
        box = rect_box
    elif size == trimmed_box[2:]:
        box = trimmed_box
    else:
        whole = rect_box == (0, 0, tex_w, tex_h)
        if problem or not whole or _others_on_texture(obj, texture_obj):
            sizes = (" " + tr("или") + " ").join(dict.fromkeys(_size_text(*b[2:]) for b in (rect_box, trimmed_box)))
            why = (
                tr("сетку спрайта нельзя заменить: {problem}", problem=problem) if problem
                else tr("спрайт занимает только часть текстуры, которую делит с другими спрайтами") if not whole
                else tr("эту текстуру использует ещё и другой спрайт")
            )
            return (
                tr("Размер изображения {size_text} не совпадает с размером спрайта — нужен {sizes}. Картинку "
                   "другого размера можно вставить только в спрайт, который один занимает всю свою текстуру, а "
                   "здесь {why}.", size_text=_size_text(*size), sizes=sizes, why=why)
            )
        note = _resize_sprite(tree, size)
        resized = True
        box = (0, 0, size[0], size[1])
        tex_w, tex_h = size

    need_mesh = not sprite_mesh.is_full_rect(tree, box, obj.version)
    if need_mesh and problem:
        if box != trimmed_box:
            return (
                tr("Картинку размера {size_text} вставить нельзя: сетку спрайта нужно заменить прямоугольником, но "
                   "{problem}. Подойдёт картинка размера {size_text2}.", size_text=_size_text(*size), problem=problem, size_text2=_size_text(*trimmed_box[2:]))
            )
        need_mesh = False
        note = (tr("сетка спрайта не изменена ({problem}) — в игре будет видна только часть картинки внутри "
           "прежнего контура", problem=problem))

    if resized:
        full_img = img.convert("RGBA")      # the picture IS the new texture
    else:
        try:
            full_img = tex_data.image.convert("RGBA")
        except Exception as e:
            return tr("Не удалось декодировать текущую текстуру спрайта: {error}\n{format_exc}", error=e, format_exc=traceback.format_exc())
        full_img.paste(img.convert("RGBA"), (box[0], full_img.height - box[1] - box[3]))

    error = _store_texture(tex_data, full_img, texture_quality)
    if error:
        return error
    _forget_decoded_texture(obj, texture_obj.path_id)

    if need_mesh or note:
        if need_mesh:
            sprite_mesh.set_full_rect(tree, box, (tex_w, tex_h), obj.version)
        try:
            obj.save_typetree(tree)
        except Exception as e:
            return tr("Текстура обновлена, но сам спрайт сохранить не удалось: {error}\n{format_exc}", error=e, format_exc=traceback.format_exc())
    return f"{IMPORT_WARNING_PREFIX}{note}" if note else None


def _resize_sprite(tree: dict, size) -> str:
    """m_Rect becomes the whole new picture; scale, borders, offset and physics outline follow (see
    _import_unpacked_sprite). Returns the note for the log."""
    rect = tree["m_Rect"]
    old_w, old_h = rect["width"], rect["height"]
    new_w, new_h = size
    fx, fy = new_w / old_w, new_h / old_h
    r = min(fx, fy)
    tree["m_Rect"] = {"x": 0.0, "y": 0.0, "width": float(new_w), "height": float(new_h)}
    tree["m_PixelsToUnits"] = tree["m_PixelsToUnits"] * r
    border = tree.get("m_Border")
    if isinstance(border, dict):
        for k in border:
            border[k] = border[k] * r
    offset = tree.get("m_Offset")
    if isinstance(offset, dict):
        offset["x"], offset["y"] = offset["x"] * fx, offset["y"] * fy
    # the outline is in units: a picture that grew along one axis more than the scale did stretches along it
    sx, sy = fx / r, fy / r
    for path in tree.get("m_PhysicsShape") or []:
        for point in path:
            point["x"], point["y"] = point["x"] * sx, point["y"] * sy

    sizes = dict(old=_size_text(int(old_w), int(old_h)), new=_size_text(new_w, new_h))
    if abs(sx - 1) < 1e-6 and abs(sy - 1) < 1e-6:
        return tr("размер спрайта изменён с {old} на {new}; в игре он останется того же размера", **sizes)
    factor = sx if sx > sy else sy
    number = f"{factor:.2f}".rstrip("0").rstrip(".")
    if current_language() in ("ru", "uk"):
        number = number.replace(".", ",")         # 1,5 — the decimal comma of these languages
    if sx > sy:
        return tr("размер спрайта изменён с {old} на {new}; в игре он станет шире в {number} раза", number=number, **sizes)
    return tr("размер спрайта изменён с {old} на {new}; в игре он станет выше в {number} раза", number=number, **sizes)
