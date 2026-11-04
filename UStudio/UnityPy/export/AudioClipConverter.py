from __future__ import annotations

from typing import TYPE_CHECKING, Dict

# Must run before fmod_toolkit is ever imported anywhere in the process — see
# Fsb5Encoder.ensure_fmod_dll_override()'s own docstring: it points
# fmod_toolkit's underlying FMOD Core runtime at the same (newer, already-
# vendored) fmod.dll the FSB5 encoder uses, instead of fmod_toolkit's own
# bundled 2.0.22 — a real, measured version gap, not a hypothetical one. Both
# directions were verified against real fixtures: existing AudioClip decoding
# (this module's own extract_audioclip_samples, used for every export/preview
# today) is unaffected, and audio freshly encoded by the FSB5 path decodes
# correctly where it previously failed under the older DLL.
from ..helpers.Fsb5Encoder import ensure_fmod_dll_override

ensure_fmod_dll_override()

import fmod_toolkit

from ..helpers.ResourceReader import get_resource_data

if TYPE_CHECKING:
    from ..classes import AudioClip


def extract_audioclip_samples(audio: AudioClip, convert_pcm_float: bool = True) -> Dict[str, bytes]:
    """extracts all the samples from an AudioClip
    :param audio: AudioClip
    :type audio: AudioClip
    :return: {filename : sample(bytes)}
    :rtype: dict
    """
    audio_data: bytes
    if audio.m_AudioData:
        audio_data = bytes(audio.m_AudioData)
    elif audio.m_Resource:
        assert audio.object_reader is not None, "AudioClip uses an external resource but object_reader is not set"
        resource = audio.m_Resource
        audio_data = get_resource_data(
            resource.m_Source,
            audio.object_reader.assets_file,
            resource.m_Offset,
            resource.m_Size,
        )
    else:
        raise ValueError("AudioClip with neither m_AudioData nor m_Resource")

    magic = memoryview(audio_data)[:8]
    if magic[:4] == b"OggS":
        return {f"{audio.m_Name}.ogg": audio_data}
    elif magic[:4] == b"RIFF":
        return {f"{audio.m_Name}.wav": audio_data}
    elif magic[4:8] == b"ftyp":
        return {f"{audio.m_Name}.m4a": audio_data}

    return fmod_toolkit.raw_to_wav(
        audio_data,
        audio.m_Name,
        audio.m_Channels or 2,
        audio.m_Frequency or 44100,
        convert_pcm_float=convert_pcm_float,
    )
