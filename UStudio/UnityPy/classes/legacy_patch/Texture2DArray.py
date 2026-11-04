from __future__ import annotations

from typing import TYPE_CHECKING, BinaryIO, List, Optional, Union

from ...enums.GraphicsFormat import GRAPHICS_TO_TEXTURE_MAP, GraphicsFormat
from ..generated import Texture2DArray

if TYPE_CHECKING:
    from PIL import Image


def _Texture2DArray_get_image_data(self: Texture2DArray):
    if self.image_data:
        return self.image_data
    if self.m_StreamData and self.m_StreamData.path:
        from ...helpers.ResourceReader import get_resource_data

        return get_resource_data(
            self.m_StreamData.path,
            self.object_reader.assets_file,
            self.m_StreamData.offset,
            self.m_StreamData.size,
        )
    raise ValueError("No image data found")


def _Texture2DArray_get_images(self: Texture2DArray) -> List[Image.Image]:
    from ...enums import BuildTarget
    from ...export import Texture2DConverter

    texture_format = GRAPHICS_TO_TEXTURE_MAP.get(GraphicsFormat(self.m_Format))
    if not texture_format:
        raise NotImplementedError(f"GraphicsFormat {self.m_Format} not supported yet")

    image_data = self.get_image_data()

    # calculate the number of textures in the array
    texture_size = self.m_DataSize // self.m_Depth

    return [
        Texture2DConverter.parse_image_data(
            image_data[offset : offset + texture_size],
            self.m_Width,
            self.m_Height,
            texture_format,
            self.object_reader.version,
            getattr(self.object_reader, "platform", BuildTarget.UnknownPlatform),
            None,
        )
        for offset in range(0, self.m_DataSize, texture_size)
    ]


def _Texture2DArray_set_images(
    self: Texture2DArray,
    images: List[Optional[Union["Image.Image", str, BinaryIO]]],
    quality: str = "balanced",
) -> None:
    """`images` must have exactly `m_Depth` entries, one per slice, in order.
    An entry of None means "keep this slice's existing compressed bytes
    unchanged" — copied byte-for-byte from the current image_data, never
    decoded/recompressed, so an untouched slice never loses quality across an
    edit that only touches a different slice (a real, deliberate design
    choice — see ROADMAP.md/CLAUDE.md's discussion of "individual slices vs.
    strictly all slices together": individual replacement won, at zero
    quality cost to the slices not being touched).

    Format is NOT user-selectable here (unlike Texture2D.set_image) — this
    always re-encodes into the array's own EXISTING TextureFormat, derived
    from `m_Format` (a GraphicsFormat) via GRAPHICS_TO_TEXTURE_MAP, the same
    lookup `.images` already uses to read. That map is many-values-to-one
    (SRGB and UNorm variants of the same channel layout both land on the same
    TextureFormat, and the module's own comment already flags it as "very
    experimental & untested") — going the reverse direction (TextureFormat ->
    a specific GraphicsFormat) to support a user-chosen target format would
    require guessing which GraphicsFormat variant (SRGB vs UNorm) the object
    originally meant, which nothing here can recover reliably. Staying
    match-original-format-only avoids that guess entirely: m_Format is never
    touched, so this can never desync image_data's actual encoding from what
    the header still claims.

    Every provided image must be exactly m_Width x m_Height — a
    Texture2DArray's slices share one fixed resolution by definition, so a
    mismatched size is a caller error, not something to silently resize
    around.

    Mip levels are not GENERATED for a replaced slice (mirrors this class's
    own `.images` getter, which already assumes exactly one mip level per
    slice via a flat `m_DataSize // m_Depth` split with no per-level
    accounting) — `m_MipCount` is forced to 1 on the whole object afterward,
    the same simplification Texture2D.set_image already makes ("disable
    mipmaps as we don't store them ourselves by default").

    Real correctness gap found and fixed while testing against a real fixture
    (sample_Texture2DArray, m_MipCount=8): an EXISTING mip-mapped array's
    per-slice byte range (`m_DataSize // m_Depth`) covers the WHOLE mip
    chain, not just the base level — so a naive byte-for-byte copy of a KEPT
    slice's full range, sitting next to a REPLACED slice's freshly-encoded
    BASE-LEVEL-ONLY bytes (necessarily shorter, since no mip chain is being
    generated), would produce chunks of unequal length. That breaks the
    fixed-stride assumption `self.m_DataSize // self.m_Depth` depends on for
    EVERY future read, not just of the slices actually touched. Since forcing
    `m_MipCount = 1` already means every slice must end up base-level-only
    regardless, the fix re-decodes a kept slice's mip chain down to just its
    base level (via the same `parse_image_data()` call `.images` already
    uses) whenever the object currently has more than one mip level, then
    treats it exactly like a freshly-provided replacement image. The
    zero-cost byte-for-byte fast path is kept for the common case (no mips to
    begin with — image_data is already base-level-only, so nothing needs
    truncating)."""
    from PIL import Image

    from ...export import Texture2DConverter
    from ...helpers.ResourceReader import get_resource_data

    if len(images) != self.m_Depth:
        raise ValueError(f"Expected {self.m_Depth} slices (m_Depth), got {len(images)}")

    texture_format = GRAPHICS_TO_TEXTURE_MAP.get(GraphicsFormat(self.m_Format))
    if not texture_format:
        raise NotImplementedError(f"GraphicsFormat {self.m_Format} not supported yet")

    current_data = self.image_data
    if not current_data:
        if self.m_StreamData is None or not self.m_StreamData.path:
            raise ValueError("No existing image data to read unchanged slices from")
        current_data = get_resource_data(
            self.m_StreamData.path,
            self.object_reader.assets_file,
            self.m_StreamData.offset,
            self.m_StreamData.size,
        )
    texture_size = self.m_DataSize // self.m_Depth
    has_existing_mips = (self.m_MipCount or 1) > 1

    platform = self.object_reader.platform if self.object_reader is not None else 0

    chunks = []
    for i, img in enumerate(images):
        if img is None:
            offset = i * texture_size
            raw_chunk = current_data[offset : offset + texture_size]
            if not has_existing_mips:
                chunks.append(bytes(raw_chunk))
                continue
            # Re-decode just to strip trailing mip levels down to the base
            # image — see the docstring above for why a raw byte copy isn't
            # safe here. object_reader.version, not self.version: matches
            # the exact call _Texture2DArray_get_images() already makes.
            img = Texture2DConverter.parse_image_data(
                raw_chunk, self.m_Width, self.m_Height, texture_format, self.object_reader.version, 0, None
            )
        if not isinstance(img, Image.Image):
            img = Image.open(img)
        if img.width != self.m_Width or img.height != self.m_Height:
            raise ValueError(
                f"Slice {i}: image is {img.width}x{img.height}, expected "
                f"{self.m_Width}x{self.m_Height} (every slice in a "
                f"Texture2DArray must share the array's own dimensions)"
            )
        img_data, _ = Texture2DConverter.image_to_texture2d(img, texture_format, platform, None, quality=quality)
        chunks.append(img_data)

    new_data = b"".join(chunks)
    self.image_data = new_data
    self.m_DataSize = len(new_data)
    if self.m_MipCount is not None:
        self.m_MipCount = 1
    if self.m_StreamData is not None:
        self.m_StreamData.path = ""
        self.m_StreamData.offset = 0
        self.m_StreamData.size = 0


Texture2DArray.images = property(_Texture2DArray_get_images)
Texture2DArray.set_images = _Texture2DArray_set_images
Texture2DArray.get_image_data = _Texture2DArray_get_image_data

__all__ = ("Texture2DArray",)
