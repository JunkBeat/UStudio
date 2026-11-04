"""Is a Raw replacement (.dump.bin) plausible for the object it is about to overwrite?

Raw import replaces an object's serialized bytes wholesale, so nothing downstream ever looks at them again:
a file of garbage, a truncated dump or a dump of another script was accepted, reported as applied and saved
(USTUDIO_CLI_KNOWN_BUGS.md, C3 - a 40-byte file `1..40` became a "SceneLocalizationSettings"). The checks here
refuse what cannot be right and stay silent about everything they cannot judge:

1. Structure. When the object's own type schema is TRUSTWORTHY - it reads the object as it is now, to the very
   last byte - the new bytes must read through it completely too. A schema that does not even read the current
   object (the generator-built one of an IL2CPP MonoBehaviour can be incomplete) proves nothing, so then this
   step says nothing.
2. MonoBehaviour identity. The script the data belongs to is a fixed spot in the bytes (the pointer after the
   game-object pointer and the enabled flag), readable without any schema, even when the script's name cannot
   be resolved (a partial load, an IL2CPP game): it must be the same one the object has now. Data carrying
   another pointer was made for another script or another build of the game, and would leave the object
   attached to the wrong script.

PyQt-free, shared by the GUI's and the CLI's Raw import (core.object_import.import_object_raw)."""

from core.i18n import N_, tr
import logging
from typing import Optional

from UnityPy.helpers import TypeTreeHelper
from UnityPy.streams import EndianBinaryReader

logger = logging.getLogger(__name__)

EMPTY_MESSAGE = N_("Файл пуст - это не данные объекта. Объект не изменён.")
SCRIPT_MESSAGE = (
    N_("Данные сделаны для другого скрипта: ссылка на скрипт внутри файла не совпадает со ссылкой в объекте "
    "(файл от другой версии игры или от другого объекта). Объект не изменён.")
)


def _structure_message(type_name: str) -> str:
    return (
        tr("Данные не подходят к этому объекту: их устройство не совпадает с устройством объекта типа "
           "«{type_name}» (файл повреждён, обрезан или сделан для другой версии игры). Объект не изменён.", type_name=type_name)
    )


def _schema_node(obj):
    try:
        return obj._get_typetree_node()
    except Exception:
        return None


def _reads_exactly(obj, node, data: bytes) -> bool:
    """True when `node` reads `data` completely: nothing missing, nothing left over."""
    try:
        reader = EndianBinaryReader(data, endian=obj.reader.endian)
        TypeTreeHelper.read_typetree(node, reader, as_dict=True, byte_size=len(data), check_read=True,
                                     assetsfile=obj.assets_file)
        return True
    except Exception:
        return False


def _script_problem(obj, data: bytes, current: bytes, type_name: str) -> Optional[str]:
    """MonoBehaviour head: PPtr<GameObject>, UInt8 m_Enabled (padded to 4), PPtr<MonoScript>, string m_Name."""
    ptr = 12 if obj.assets_file.header.version >= 14 else 8   # int32 file + (int64 | int32) path
    script_at = ptr + 4
    name_at = script_at + ptr
    if len(current) < name_at + 4:
        return None  # the object itself has no readable head: nothing to compare against
    if len(data) < name_at + 4:
        return _structure_message(type_name)
    if data[script_at:name_at] != current[script_at:name_at]:
        return tr(SCRIPT_MESSAGE)
    order = "big" if obj.reader.endian == ">" else "little"
    name_len = int.from_bytes(data[name_at:name_at + 4], order, signed=True)
    if name_len < 0 or name_at + 4 + name_len > len(data):
        return _structure_message(type_name)
    return None


def raw_replacement_problem(obj, data: bytes) -> Optional[str]:
    """None when `data` may replace obj's serialized bytes, else a complete, user-facing reason (the object
    is not touched in that case). Never raises: a check that cannot run lets the data through, because
    refusing good data over a failure of the check itself would be the worse mistake."""
    if not data:
        return tr(EMPTY_MESSAGE)
    try:
        type_name = getattr(getattr(obj, "type", None), "name", "") or "?"
        current_bytes: Optional[bytes] = None

        def current() -> bytes:
            nonlocal current_bytes
            if current_bytes is None:
                current_bytes = obj.data if obj.data is not None else obj.get_raw_data()
            return current_bytes

        node = _schema_node(obj)
        if node is not None and not _reads_exactly(obj, node, data) and _reads_exactly(obj, node, current()):
            return _structure_message(type_name)
        if type_name == "MonoBehaviour":
            return _script_problem(obj, data, current(), type_name)
        return None
    except Exception:
        logger.debug("Проверка Raw-данных не выполнена", exc_info=True)
        return None
