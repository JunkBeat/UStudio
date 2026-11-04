"""BC1-BC7 texture compression via BCnEncoder.NET (loaded in-process through
pythonnet/.NET CoreCLR), as a quality-tunable alternative to etcpak's BC
encoders for exactly the formats etcpak's own BC output is not good enough
for (see Texture2DConverter.compress_etcpak's docstring for the split).

Real bug found and fixed while wiring this up (not ported from the reference
implementation this was adapted from): that implementation built a full DDS
file via BcEncoder/BCnEncoderExtensions.EncodeToStream() and then sliced
`[128:]` to strip the DDS header, on the assumption the header is always
exactly 128 bytes. Measured directly against this exact encoder/library
version: the header is actually 68 bytes for BOTH a legacy-FourCC format
(BC1) and a DX10-extended-header format (BC7) — slicing at 128 discards the
first 60 bytes of REAL COMPRESSED PIXEL DATA every single time, for every
format, not just BC7. This is avoided entirely here by using
BCnEncoderExtensions.EncodeToRawBytes() instead, which returns the raw
per-mip compressed block bytes with no container to strip in the first
place — verified byte-length-exact (width/4 * height/4 * bytes-per-block)
and round-tripped through texture2ddecoder for both BC1 and BC7.

The DLLs this loads (BCnEncoder.dll, BCnEncoder.NET.ImageSharp.dll,
CommunityToolkit.HighPerformance.dll, SixLabors.ImageSharp.dll — all MIT/
Apache-licensed) live under UnityPy/resources/bcn_encoder/, vendored the
same way UnityPyBoost's prebuilt .pyd and lzma.tpk already are elsewhere in
this project — real binaries checked into the repo rather than fetched at
run time, since this app has no installer/package step of its own.
"""

import os
import threading
from pathlib import Path
from typing import List, Optional, Union

from ..enums.TextureFormat import TextureFormat

_LOCK = threading.Lock()
_initialized = False

# Same fix, same root cause, as Fsb5Encoder.py's identical _RESOURCE_DIR —
# see that module's comment for the full explanation (importlib.resources.
# files() on a dynamically-named package breaks under Nuitka --standalone;
# this file had the exact same pattern, found by grepping for it rather than
# only fixing the one that was actually reported).
#
# Second, separate real bug, found later testing the built CLI exe's
# --onefile mode specifically — see Fsb5Encoder.py's own second comment for
# the full explanation (Nuitka's package-config DLL plugin only bundles a
# module's files if that module is actually `import`-ed somewhere, not just
# named in the YAML config; confirmed via an isolated minimal repro). Fixed
# here for the identical reason, not left half-done alongside the other two.
import UnityPy.resources.bcn_encoder  # noqa: F401

_RESOURCE_DIR = Path(__file__).resolve().parent.parent / "resources" / "bcn_encoder"

# BCnEncoder.NET's own CompressionFormat enum members these map to are
# resolved lazily (see _ensure_loaded) — this project doesn't import System.*
# types until the CLR is actually loaded, so this only names the strings.
_FORMAT_TO_BC = {
    TextureFormat.DXT1: "Bc1",
    TextureFormat.DXT1Crunched: "Bc1",
    TextureFormat.DXT3: "Bc2",
    TextureFormat.DXT5: "Bc3",
    TextureFormat.DXT5Crunched: "Bc3",
    TextureFormat.BC4: "Bc4",
    TextureFormat.BC5: "Bc5",
    TextureFormat.BC7: "Bc7",
    # ATC — verified end-to-end against this project's OWN decoder before
    # being added here (not assumed just because the enum member exists —
    # see the note below on why that caution was warranted). TF.ATC_RGBA8
    # maps to AtcInterpolatedAlpha specifically, NOT AtcExplicitAlpha — see
    # the ATC section below for why the two are not interchangeable.
    TextureFormat.ATC_RGB4: "Atc",
    TextureFormat.ATC_RGBA8: "AtcInterpolatedAlpha",
}

# Checked via reflection (System.Enum.GetNames(CompressionFormat)) against
# Unity's own TextureFormat enum, per an explicit request not to assume
# coverage: BCnEncoder.NET's CompressionFormat also has R/Rg/Rgb/Rgba/Bgra
# (uncompressed — already handled elsewhere in image_to_texture2d, no need
# to route those here) and Bc6U/Bc6S (HDR — no HDR TextureFormat exists in
# this project's target Unity versions, not applicable).
#
# ATC (TF.ATC_RGB4/TF.ATC_RGBA8, wired in above) previously fell through
# image_to_texture2d's raw-RGB24 fallback — neither etcpak nor astc_encoder
# support ATC encoding at all, so this was a real, previously-unclaimed
# opportunity. Verified properly before wiring in, not assumed just because
# the CompressionFormat enum has matching members — an early smoke test
# looked alarming (Atc/AtcExplicitAlpha/AtcInterpolatedAlpha on a real
# texture all scored an identical 22.36 dB PSNR against texture2ddecoder's
# decode_atc_rgb4/decode_atc_rgba8, which reads exactly like an
# encoder-decoder bitstream mismatch). Root-caused instead of accepted at
# face value: that texture happens to be fully opaque, so the three modes'
# byte-identical color blocks decode identically regardless of which alpha
# scheme was nominally chosen — not a bug. Confirmed genuinely correct via a
# solid-color 8x8 block (encoded color endpoints, once actually decoded
# right, matched the known source color to within 1 unit per channel) and
# via a real alpha gradient decoded through decode_atc_rgba8 — which is
# where AtcExplicitAlpha vs AtcInterpolatedAlpha stopped being
# interchangeable: AtcInterpolatedAlpha reproduced the gradient almost
# exactly (0,66,131,196,255 vs the source's 0,64,128,191,255),
# AtcExplicitAlpha was consistently off by 16-24 (consistent with a
# coarser, non-interpolated 4-bit alpha quantization) — confirming
# AssetStudio's decode_atc_rgba8 (which this project's texture2ddecoder
# wraps) expects the interpolated scheme specifically, matching its own
# documented use of a BC3-style alpha block. Quality-wise, ATC lands close
# to BC1 at the same 4bpp bit budget on a real busy texture (22.36 dB vs
# BC1's 23.66 dB) — a reasonable, working format, not a downgrade from
# "nothing" the way the previous raw-RGB24 substitution was.
#
# Bc1WithAlpha (DXT1's punch-through alpha mode) was previously left
# deliberately unwired, per an earlier investigation that found this
# project's preview decoder — texture2ddecoder.decode_bc1, wrapping Perfare/
# AssetStudio's bcn.cpp — hardcodes color(0,0,0,255) for the punch-through
# index instead of writing alpha=0. Re-checked before finally wiring this in
# (per this project's own "verify a memory before trusting it" rule) and
# found that note was STALE: this project's actual live DXT1 DECODE path
# (see the "pillow" dispatch table below, TF.DXT1 -> the "bcn" raw decoder)
# is Pillow's own native BC1 decoder, not texture2ddecoder.decode_bc1 at all
# — confirmed via a hand-built BC1 block with the punch-through convention
# (color0=0x0000 <= color1=0xFFFF, all indices=3) decoding to correct
# alpha=0, not the old bug's black. Verified end-to-end with the REAL
# encoder too, not just a synthetic block: a genuine BCnEncoder.NET
# Bc1WithAlpha encode of a real half-transparent 8x8 test image (left half
# opaque red, right half fully transparent), decoded through this exact
# "bcn" plugin, reproduced the source exactly — sharp transition, alpha=0 on
# the transparent half, no bleed. Now wired in: compress_bc() picks
# "Bc1WithAlpha" over plain "Bc1" automatically whenever the source data
# actually has a non-fully-opaque pixel (see _has_real_transparency below) —
# this closes a real, separate correctness gap discovered along the way, not
# just a preview cosmetic one: plain "Bc1" never represents transparency at
# all (BCnEncoder.NET's own "opaque" mode), so every DXT1-targeted texture
# with real source transparency imported through this pipeline before this
# fix had its alpha channel silently discarded on import, not merely
# mis-previewed.
#
# etcpak (still used for ETC1/ETC2 below) has no matching gap check needed —
# it never claimed to support anything BCnEncoder.NET now also supports, and
# every format this module DOES claim (_FORMAT_TO_BC above) BCnEncoder.NET
# actually implements and was verified to round-trip correctly through this
# project's own decoder — no format in this dict is wired in on assumption
# alone.

# Every format always uses BestQuality; the `quality` arguments below are accepted and ignored
# (measured 2026-10-20, 21 real textures): "Balanced" is no faster for BC1-BC5 or ATC, and its
# colour search lets an endpoint go below 0 and wrap (a block with blue = 0 everywhere got an
# endpoint with blue 28 of 31: cyan specks in green areas; BC1: 530 such blocks in the set against
# 13 with BestQuality; ATC on Kindergarten «FinalPicture»: 28.9 vs 36.8 dB). BC7 no longer comes
# here (Texture2DConverter.compress_bc7_etcpak).
_QUALITY = "BestQuality"

# Populated by _ensure_loaded(): the actual .NET types/functions, kept as
# module globals rather than re-imported per call (clr.AddReference()+import
# is not free, and compress_bc() can run once per object in a bulk import).
_BcEncoder = None
_BCnEncoderExtensions = None
_CompressionFormat = None
_CompressionQuality = None
_OutputFileFormat = None
_ImageSharpImage = None
_Rgba32 = None
_MemoryStream = None


def _ensure_loaded() -> None:
    global _initialized, _BcEncoder, _BCnEncoderExtensions, _CompressionFormat
    global _CompressionQuality, _OutputFileFormat, _ImageSharpImage, _Rgba32, _MemoryStream

    if _initialized:
        return
    with _LOCK:
        if _initialized:
            return

        lib_dir = str(_RESOURCE_DIR)
        runtime_config = os.path.join(lib_dir, "runtimeconfig.json")

        # Must happen before the FIRST "import clr" anywhere in the process —
        # pythonnet locks in whichever runtime backend gets configured first.
        from clr_loader import get_coreclr
        from pythonnet import set_runtime

        set_runtime(get_coreclr(runtime_config=runtime_config))

        import clr

        for filename in os.listdir(lib_dir):
            if filename.endswith(".dll"):
                clr.AddReference(os.path.join(lib_dir, filename))

        from BCnEncoder.Encoder import BcEncoder, CompressionQuality
        from BCnEncoder.ImageSharp import BCnEncoderExtensions
        from BCnEncoder.Shared import CompressionFormat, OutputFileFormat
        from SixLabors.ImageSharp import Image as ImageSharpImage
        from SixLabors.ImageSharp.PixelFormats import Rgba32
        from System.IO import MemoryStream

        _BcEncoder = BcEncoder
        _BCnEncoderExtensions = BCnEncoderExtensions
        _CompressionFormat = CompressionFormat
        _CompressionQuality = CompressionQuality
        _OutputFileFormat = OutputFileFormat
        _ImageSharpImage = ImageSharpImage
        _Rgba32 = Rgba32
        _MemoryStream = MemoryStream
        _initialized = True


def supports_format(target_texture_format: Union[TextureFormat, int]) -> bool:
    return TextureFormat(target_texture_format) in _FORMAT_TO_BC


def _load_image_sharp(data: bytes, width: int, height: int):
    """Bridges raw RGBA8888 bytes into a SixLabors.ImageSharp Image<Rgba32> via
    a PNG round trip. SixLabors.ImageSharp does expose
    Image.LoadPixelData<T>(ReadOnlySpan<T>, ...) and Image<T> also has
    WrapMemory(Memory<T>, ...) — both would skip the PNG encode/decode, but
    ReadOnlySpan<T>/Memory<T> are marshalled by pythonnet only as opaque CLR
    objects it cannot construct FROM a Python bytes/array in one step (no
    public Image<Rgba32> constructor accepts a raw pixel array either —
    checked via reflection: only (Configuration, w, h[, fill-color]) ctors
    exist). The PNG round trip is the one path proven to work end-to-end
    (verified via direct testing), and its cost is negligible next to BC7's
    own compression time (measured: ~0.5-30s depending on size/quality) —
    this runs once per imported texture, not in a hot loop, so it isn't worth
    more CLR-interop risk to shave off a millisecond-scale PNG encode."""
    import io
    from PIL import Image as PILImage

    pil_img = PILImage.frombytes("RGBA", (width, height), data)
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")

    ms = _MemoryStream(buf.getvalue())
    try:
        return _ImageSharpImage.Load[_Rgba32](ms)
    finally:
        ms.Dispose()


_DXT1_LIKE_FORMATS = (TextureFormat.DXT1, TextureFormat.DXT1Crunched)


def _has_real_transparency(data: bytes) -> bool:
    """True if raw RGBA8888 `data` has at least one not-fully-opaque pixel.
    Used to decide Bc1 vs Bc1WithAlpha for a DXT1 target — see this module's
    own docstring above for why plain Bc1 silently discards ANY transparency
    at all (it's BCnEncoder.NET's "never use the punch-through convention"
    mode), so this check gates real correctness, not just a quality knob.
    Cheap: a single strided slice + an any() over the alpha channel, no
    decode/copy of the RGB channels needed."""
    alpha = memoryview(data)[3::4]
    return any(b != 255 for b in alpha)


def _make_encoder(target_texture_format: TextureFormat, quality: str, mip_levels: int, data: Optional[bytes] = None):
    bc_name = _FORMAT_TO_BC.get(target_texture_format)
    if bc_name is None:
        raise NotImplementedError(f"No BCnEncoder.NET mapping for {target_texture_format.name}")
    if target_texture_format in _DXT1_LIKE_FORMATS and data is not None and _has_real_transparency(data):
        bc_name = "Bc1WithAlpha"

    encoder = _BcEncoder()
    encoder.OutputOptions.GenerateMipMaps = mip_levels != 1
    encoder.OutputOptions.MaxMipMapLevel = mip_levels
    encoder.OutputOptions.Format = getattr(_CompressionFormat, bc_name)
    encoder.OutputOptions.Quality = getattr(_CompressionQuality, _QUALITY)
    return encoder


# Single-channel 8-byte blocks (BC4 layout) inside each format's block: (block size,
# ((byte offset in the block, RGBA channel it stores), ...)).
_SINGLE_CHANNEL_BLOCKS = {
    TextureFormat.DXT5: (16, ((0, 3),)),
    TextureFormat.DXT5Crunched: (16, ((0, 3),)),
    TextureFormat.BC4: (8, ((0, 0),)),
    TextureFormat.BC5: (16, ((0, 0), (8, 1))),
}


def _decode_bc4_blocks(blocks):
    """(N, 8) uint8 BC4 blocks -> (N, 16) int32 values, pixel order of the block."""
    import numpy as np

    a0 = blocks[:, 0].astype(np.int32)
    a1 = blocks[:, 1].astype(np.int32)
    bits = np.zeros(len(blocks), np.uint64)
    for i in range(6):
        bits |= blocks[:, 2 + i].astype(np.uint64) << np.uint64(8 * i)
    idx = np.stack([(bits >> np.uint64(3 * k)) & np.uint64(7) for k in range(16)], 1).astype(np.int32)
    eight = a0 > a1
    pal = np.zeros((len(blocks), 8), np.int32)
    pal[:, 0] = a0
    pal[:, 1] = a1
    for k in range(1, 7):
        pal[:, 1 + k] = np.where(eight, ((7 - k) * a0 + k * a1) // 7, 0)
    for k in range(1, 5):
        pal[:, 1 + k] = np.where(eight, pal[:, 1 + k], ((5 - k) * a0 + k * a1) // 5)
    pal[:, 6] = np.where(eight, pal[:, 6], 0)
    pal[:, 7] = np.where(eight, pal[:, 7], 255)
    return np.take_along_axis(pal, idx, 1)


def _pick_better_single_channel_blocks(encoded: bytes, data: bytes, width: int, height: int, fmt: TextureFormat) -> bytes:
    """BC3's alpha, BC4 and BC5: BCnEncoder.NET puts every block holding a 0 or 255 value into
    the 6-value + explicit 0/255 mode and never tries the 8-value mode with 0/255 as an endpoint,
    which is the exact answer for many real blocks (measured 2026-10-20: Phoenix icon alpha 63 dB,
    every block in 6-value mode; etcpak 85 dB). etcpak tries both modes but is weaker elsewhere, so
    each block keeps whichever of the two decodes closer to the source. Never worse than either
    (squared error per block); ~0.01 s. Any failure keeps BCnEncoder's blocks."""
    layout = _SINGLE_CHANNEL_BLOCKS.get(fmt)
    if layout is None or width % 4 or height % 4:
        return encoded
    try:
        import etcpak
        import numpy as np

        compress = {
            TextureFormat.DXT5: etcpak.compress_bc3,
            TextureFormat.DXT5Crunched: etcpak.compress_bc3,
            TextureFormat.BC4: etcpak.compress_bc4,
            TextureFormat.BC5: etcpak.compress_bc5,
        }[fmt]
        # A fresh copy: etcpak swaps R and B in place in the buffer it is given.
        other = compress(bytes(bytearray(data)), width, height)
        block_size, channels = layout
        ours = np.frombuffer(encoded, np.uint8).reshape(-1, block_size).copy()
        theirs = np.frombuffer(other, np.uint8).reshape(-1, block_size)
        if ours.shape != theirs.shape:
            return encoded
        src = np.frombuffer(data, np.uint8).reshape(height // 4, 4, width // 4, 4, 4)
        src = src.transpose(0, 2, 1, 3, 4).reshape(-1, 16, 4).astype(np.int32)
        for offset, channel in channels:
            a = ours[:, offset:offset + 8]
            b = theirs[:, offset:offset + 8]
            err_a = ((_decode_bc4_blocks(a) - src[..., channel]) ** 2).sum(1)
            err_b = ((_decode_bc4_blocks(b) - src[..., channel]) ** 2).sum(1)
            better = err_b < err_a
            ours[better, offset:offset + 8] = b[better]
        return ours.tobytes()
    except Exception:
        return encoded


def compress_bc(
    data: bytes,
    width: int,
    height: int,
    target_texture_format: Union[TextureFormat, int],
    quality: str = "balanced",
) -> bytes:
    """Compresses raw RGBA8888 bytes (row-major, top-to-bottom — the same
    orientation Texture2DConverter.image_to_texture2d's own img.tobytes("raw",
    "RGBA") already produces) to a single base-level image in the given BC
    format. `quality` is accepted and ignored (always the best mode). Drop-in replacement
    for compress_etcpak() for the formats this module covers (see
    supports_format()) — same (data, width, height, target_format) shape, one
    level in, one level of compressed bytes out.

    Real bug found and fixed while building this (not present in the
    reference implementation this module's approach was informed by, which
    made the identical mistake, later confirmed by directly measuring its
    output): getting compressed bytes via BcEncoder normally means building a
    whole DDS file (BCnEncoderExtensions.EncodeToStream()) and then slicing
    off the header — the reference hardcoded a `[128:]` slice, which is wrong
    for this exact encoder/library version regardless of format (measured:
    the real header is 68 bytes for both a legacy-FourCC format (BC1) and a
    DX10-extended-header one (BC7) — the fixed 128 count silently discards
    the first 60 bytes of real compressed pixel data every time, corrupting
    the start of every texture this touches). Avoided entirely here by using
    BCnEncoderExtensions.EncodeToRawBytes() instead, which returns the raw
    per-mip compressed block bytes with no container to strip in the first
    place — verified byte-length-exact (width/4 * height/4 * bytes-per-block)
    and round-tripped through texture2ddecoder for both BC1 and BC7."""
    _ensure_loaded()
    target_texture_format = TextureFormat(target_texture_format)

    input_image = _load_image_sharp(data, width, height)
    try:
        encoder = _make_encoder(target_texture_format, quality, mip_levels=1, data=data)
        raw_mips = _BCnEncoderExtensions.EncodeToRawBytes(encoder, input_image)
        return _pick_better_single_channel_blocks(bytes(raw_mips[0]), data, width, height, target_texture_format)
    finally:
        input_image.Dispose()


def compress_bc_mipchain(
    data: bytes,
    width: int,
    height: int,
    target_texture_format: Union[TextureFormat, int],
    quality: str = "balanced",
    mip_count: Optional[int] = None,
) -> List[bytes]:
    """Like compress_bc(), but returns a full mip chain — base level first,
    then each successively smaller level, exactly the order Unity's own
    inline image_data expects them concatenated in (confirmed against the
    reference implementation's own equivalent, which builds this same order
    the slow way — see below). mip_count=None (the default) generates the
    full chain down to 1x1; otherwise the given number of levels.

    This is a genuine improvement over the reference implementation this
    module's approach was informed by, not a port of it: that code generated
    each mip level from PYTHON — manually PIL-resizing the source image
    (bilinear, in sRGB space, not gamma-correct) down one step at a time and
    re-invoking the WHOLE single-level encode path (a separate PNG round
    trip and a separate BcEncoder instance) once per level. BcEncoder already
    generates its own mip chain natively in one call when
    OutputOptions.GenerateMipMaps/MaxMipMapLevel are set — confirmed via
    direct testing (a 256x256 source with MaxMipMapLevel=-1 produced all 9
    levels down to 1x1 in one EncodeToRawBytes call, each level's byte count
    matching the expected block-compressed size) — so this calls it once
    instead of once per level, and lets the same library that understands
    the pixel/block format do the downsampling instead of a separately
    maintained Python resize loop that could quietly drift from it."""
    _ensure_loaded()
    target_texture_format = TextureFormat(target_texture_format)

    input_image = _load_image_sharp(data, width, height)
    try:
        # Checking just the base level's alpha is deliberate, not a shortcut:
        # if the base image has real transparency, every mip generated from
        # it will too (downsampling doesn't manufacture full opacity out of
        # transparent source pixels) — one check covers the whole chain.
        encoder = _make_encoder(target_texture_format, quality, mip_levels=mip_count if mip_count else -1, data=data)
        raw_mips = _BCnEncoderExtensions.EncodeToRawBytes(encoder, input_image)
        return [bytes(m) for m in raw_mips]
    finally:
        input_image.Dispose()
