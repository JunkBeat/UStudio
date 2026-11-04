"""ETC1 / ETC2 RGB / ETC2 RGBA8 texture compression through etc_encoder.dll
(UnityPy/resources/etc_encoder/) instead of etcpak (upstream issue #238:
etcpak's ETC2_RGBA8 is visibly blurry).

The DLL is Ericsson's etcpak 2.74 as shipped in AMD Compressonator, in its
fast perceptual mode — byte for byte the output of `compressonatorcli -fd
ETC2_RGBA` (checked on 10 real game textures), without its 160 MB of
dependencies. Source and build script: native/etc_encoder/ at the top of the
UStudio repository.

Measured on 10 real textures (Android games' ETC2/RGBA32 textures, Windows
games' painted cut-outs), PSNR of the visible pixels, decoded with
texture2ddecoder (Compressonator's own decoder gives the same pixels):
ETC2_RGBA8 36.7 -> 48.2 dB (alpha 51.7 -> 73.0), ETC2_RGB 36.4 -> 47.0,
ETC1 33.5 -> 37.2; better on every image. Cost: ~0.3 s per megapixel on 8
threads (etcpak: ~0.01 s). etcpack's exhaustive mode gained little and took
24 s for one 256 x 256 texture, so it is not offered.
"""

import ctypes
import os
import threading
from pathlib import Path
from typing import Optional

from ..enums.TextureFormat import TextureFormat

# Same reason as BcnEncoder.py: Nuitka bundles a resource folder only when its module is imported.
import UnityPy.resources.etc_encoder  # noqa: F401

_RESOURCE_DIR = Path(__file__).resolve().parent.parent / "resources" / "etc_encoder"

_KIND = {
    TextureFormat.ETC_RGB4: 0,
    TextureFormat.ETC_RGB4Crunched: 0,
    TextureFormat.ETC2_RGB: 1,
    TextureFormat.ETC2_RGBA8: 2,
    TextureFormat.ETC2_RGBA8Crunched: 2,
    TextureFormat.ETC2_RGBA1: 2,
}

_LOCK = threading.Lock()
_dll: Optional[ctypes.CDLL] = None
_load_error: Optional[str] = None


def _load() -> Optional[ctypes.CDLL]:
    global _dll, _load_error
    with _LOCK:
        if _dll is None and _load_error is None:
            try:
                dll = ctypes.CDLL(str(_RESOURCE_DIR / "etc_encoder.dll"))
                dll.etc_encode.restype = ctypes.c_int
                dll.etc_encode.argtypes = [
                    ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                    ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                ]
                _dll = dll
            except OSError as e:  # not Windows, or the DLL is missing
                _load_error = str(e)
        return _dll


def supports(texture_format: TextureFormat) -> bool:
    """True when this encoder handles the format AND the DLL loads here."""
    return texture_format in _KIND and _load() is not None


def compress_etc(data: bytes, width: int, height: int, texture_format: TextureFormat) -> bytes:
    """`data` = RGBA32 pixels, width and height multiples of 4 (image_to_texture2d pads)."""
    kind = _KIND[texture_format]
    dll = _load()
    if dll is None:
        raise RuntimeError(f"etc_encoder.dll could not be loaded: {_load_error}")
    if len(data) != width * height * 4:
        raise ValueError(f"expected {width * height * 4} bytes of RGBA data, got {len(data)}")
    size = (width // 4) * (height // 4) * (16 if kind == 2 else 8)
    out = ctypes.create_string_buffer(size)
    # ctypes releases the GIL during the call; the DLL uses one thread per CPU itself.
    written = dll.etc_encode(bytes(data), width, height, kind, 0, 1, 0, out, size)
    if written != size:
        raise RuntimeError(f"etc_encoder failed for {width}x{height} {texture_format.name}")
    return out.raw
