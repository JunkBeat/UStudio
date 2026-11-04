import ntpath
from typing import TYPE_CHECKING

from ..streams import EndianBinaryReader

if TYPE_CHECKING:
    from ..files.SerializedFile import SerializedFile


def get_resource_data(res_path: str, assets_file: "SerializedFile", offset: int, size: int):
    basename = ntpath.basename(res_path)
    name, ext = ntpath.splitext(basename)
    possible_names = [
        basename,
        f"{name}.resource",
        f"{name}.assets.resS",
        f"{name}.resS",
    ]
    environment = assets_file.environment

    # Real confirmed bug (FMOD FORMAT errors on perfectly valid AudioClips):
    # possible_names lists several historically-used naming conventions on
    # the assumption that at most ONE of them physically exists per assets
    # file, so treating a cache hit on ANY of them as equally valid is
    # normally safe. That assumption breaks when a game ships BOTH a
    # "{name}.resource" (AudioClip's own convention) AND a same-basename
    # "{name}.assets.resS" (Texture2D/Mesh's own streaming convention) for
    # ONE assets file — two real, differently-sized files with unrelated
    # content. If the .resS one happens to already be cached (e.g. a
    # Texture2D in the same file was browsed first, registering it), the
    # loop below used to grab it immediately via its first cache hit —
    # NEVER even attempting the AudioClip's own exact declared name — and
    # silently read the AudioClip's offset out of a completely different
    # file. Confirmed via a live repro: the wrong file's reader.Length
    # matched the .resS file exactly, while an independent direct read of
    # the correctly-named file at the same offset returned valid FSB5
    # header bytes.
    #
    # Fix: always resolve the EXACT declared name first (loading it if not
    # yet cached) before ever considering the alternate naming conventions
    # below — those remain exactly as before for the common case where only
    # one such file exists.
    #
    # get_cab_near(): when several loose copies of the same-named resource are
    # loaded (two sub-folders of a game folder each with their own
    # resources.assets.resS), the one closest to the assets file being read wins.
    reader = environment.get_cab_near(basename, assets_file)
    if not reader:
        assets_file.load_dependencies([basename])
        reader = environment.get_cab_near(basename, assets_file)

    if not reader:
        for possible_name in possible_names:
            reader = environment.get_cab_near(possible_name, assets_file)
            if reader:
                break
    if not reader:
        assets_file.load_dependencies(possible_names)
        for possible_name in possible_names:
            reader = environment.get_cab_near(possible_name, assets_file)
            if reader:
                break
        if not reader:
            raise FileNotFoundError(f"Resource file {basename} not found")
    return _get_resource_data(reader, offset, size)


def _get_resource_data(reader: EndianBinaryReader, offset: int, size: int):
    reader.Position = offset
    return reader.read_bytes(size)
