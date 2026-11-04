from __future__ import annotations

from sys import version_info as py_version_info
from typing import TYPE_CHECKING, Any, Optional, Union

from attrs import define

from .. import classes
from ..streams.EndianBinaryReader import EndianBinaryReader
from ..streams.EndianBinaryWriter import EndianBinaryWriter
from .TypeTreeNode import TypeTreeNode

Object = classes.Object
UnknownObject = classes.UnknownObject
PPtr = classes.PPtr

if TYPE_CHECKING:
    from ..files.SerializedFile import SerializedFile


try:
    from ..UnityPyBoost import read_typetree as read_typetree_boost
except ImportError:
    read_typetree_boost = None

kAlignBytes = 0x4000

FUNCTION_READ_MAP = {
    "SInt8": EndianBinaryReader.read_byte,
    "UInt8": EndianBinaryReader.read_u_byte,
    "char": EndianBinaryReader.read_u_byte,
    "short": EndianBinaryReader.read_short,
    "SInt16": EndianBinaryReader.read_short,
    "unsigned short": EndianBinaryReader.read_u_short,
    "UInt16": EndianBinaryReader.read_u_short,
    "int": EndianBinaryReader.read_int,
    "SInt32": EndianBinaryReader.read_int,
    "unsigned int": EndianBinaryReader.read_u_int,
    "UInt32": EndianBinaryReader.read_u_int,
    "Type*": EndianBinaryReader.read_u_int,
    "long long": EndianBinaryReader.read_long,
    "SInt64": EndianBinaryReader.read_long,
    "unsigned long long": EndianBinaryReader.read_u_long,
    "UInt64": EndianBinaryReader.read_u_long,
    "FileSize": EndianBinaryReader.read_u_long,
    "float": EndianBinaryReader.read_float,
    "double": EndianBinaryReader.read_double,
    "bool": EndianBinaryReader.read_boolean,
    "string": EndianBinaryReader.read_aligned_string,
    "TypelessData": EndianBinaryReader.read_byte_array,
}

FUNCTION_READ_MAP_ARRAY = {
    "SInt8": EndianBinaryReader.read_byte_array,
    "UInt8": EndianBinaryReader.read_u_byte_array,
    "char": EndianBinaryReader.read_u_byte_array,
    "short": EndianBinaryReader.read_short_array,
    "SInt16": EndianBinaryReader.read_short_array,
    "unsigned short": EndianBinaryReader.read_u_short_array,
    "UInt16": EndianBinaryReader.read_u_short_array,
    "int": EndianBinaryReader.read_int_array,
    "SInt32": EndianBinaryReader.read_int_array,
    "unsigned int": EndianBinaryReader.read_u_int_array,
    "UInt32": EndianBinaryReader.read_u_int_array,
    "Type*": EndianBinaryReader.read_u_int_array,
    "long long": EndianBinaryReader.read_long_array,
    "SInt64": EndianBinaryReader.read_long_array,
    "unsigned long long": EndianBinaryReader.read_u_long_array,
    "UInt64": EndianBinaryReader.read_u_long_array,
    "FileSize": EndianBinaryReader.read_u_long_array,
    "float": EndianBinaryReader.read_float_array,
    "double": EndianBinaryReader.read_double_array,
    "bool": EndianBinaryReader.read_boolean_array,
}


@define(slots=True)
class TypeTreeConfig:
    as_dict: bool
    assetsfile: "Optional[SerializedFile]" = None
    has_registry: bool = False

    def copy(self) -> TypeTreeConfig:
        return TypeTreeConfig(self.as_dict, self.assetsfile, self.has_registry)


def get_ref_type_node(ref_object: dict, assetfile: SerializedFile) -> Optional[TypeTreeNode]:
    typ = ref_object["type"]
    if isinstance(typ, dict):
        cls = typ["class"]
        ns = typ["ns"]
        asm = typ["asm"]
    else:
        cls = getattr(typ, "class")
        ns = typ.ns
        asm = typ.asm

    if not assetfile or not assetfile.ref_types:
        raise ValueError("SerializedFile has no ref_types")

    if cls == "":
        return None

    for ref_type in assetfile.ref_types:
        if cls == ref_type.m_ClassName and ns == ref_type.m_NameSpace and asm == ref_type.m_AssemblyName:
            return ref_type.node
    else:
        raise ValueError(f"Referenced type not found: {cls} {ns} {asm}")


if py_version_info >= (3, 14):
    from annotationlib import get_annotations as annotationlib_get_annotations

    def get_annotation_keys(clz) -> set[str]:
        return set(annotationlib_get_annotations(clz).keys())
else:

    def get_annotation_keys(clz) -> set[str]:
        return set(clz.__annotations__)


def read_typetree(
    root_node: TypeTreeNode,
    reader: EndianBinaryReader,
    as_dict: bool = True,
    byte_size: Optional[int] = None,
    check_read: bool = True,
    assetsfile: Optional[SerializedFile] = None,
    use_boost: bool = True,
) -> Union[dict[str, Any], Object]:
    """Reads the typetree of the object contained in the reader via the node list.

    Parameters
    ----------
    nodes : list
        List of nodes/nodes
    reader : EndianBinaryReader
        Reader of the object to be parsed
    use_boost : bool
        Whether the compiled UnityPyBoost accelerator may be used when available.
        Pass False to force the pure-Python fallback. Exists as a debugging escape
        hatch: UnityPyBoost/TypeTreeHelper.cpp's read_typetree() once had a real bug
        here — it parsed the `endian` argument's "C" format code (which the Python
        C API always writes as a 4-byte int) into a 1-byte `char`, corrupting
        whatever adjacent stack memory the extra 3 bytes landed on. That surfaced as
        PPtr m_FileID/m_PathID occasionally coming back byte-swapped (e.g. a true
        m_FileID of 1 read back as 16777216 = 0x01000000). Fixed at the source
        (parse into a proper `int`, narrow afterward) and rebuilt; use_boost is kept
        as a quick way to bisect "boost vs pure-Python" if a similar issue ever
        resurfaces, not because the fix is in doubt.

    Returns
    -------
    dict | objects.Object
        The parsed typtree
    """
    bytes_read: int
    data = None
    if byte_size and use_boost and read_typetree_boost:
        data = reader.read_bytes(byte_size)
        obj, bytes_read = read_typetree_boost(data, root_node, reader.endian, as_dict, assetsfile, classes)
    else:
        pos = reader.Position
        config = TypeTreeConfig(as_dict, assetsfile, False)
        obj = read_value(root_node, reader, config)
        bytes_read = reader.Position - pos

    if check_read and bytes_read != byte_size:
        if not _is_zero_padded_text_asset(root_node, reader, data, bytes_read, byte_size):
            raise ValueError(f"Expected to read {byte_size} bytes, but only read {bytes_read} bytes")

    return obj


def _is_zero_padded_text_asset(
    root_node: TypeTreeNode,
    reader: EndianBinaryReader,
    data: Optional[bytes],
    bytes_read: int,
    byte_size: Optional[int],
) -> bool:
    """A TextAsset read in full, followed only by zero bytes up to its stored size.

    Some translation tools write a shorter text in place and fill the rest of the
    object with zeros instead of shrinking it; the game ignores the tail. Only for
    TextAsset: for a MonoBehaviour a zero tail is just as likely to be script
    fields the layout lacks (they would be lost on save)."""
    if root_node.m_Type != "TextAsset" or not byte_size or bytes_read >= byte_size:
        return False
    if data is not None:
        tail = data[bytes_read:byte_size]
    else:
        end = reader.Position
        tail = reader.read_bytes(byte_size - bytes_read)
        reader.Position = end
    return len(tail) == byte_size - bytes_read and not any(tail)

    return obj


def read_typetree_from_bytes(
    data: bytes,
    root_node: TypeTreeNode,
    endian: str,
    as_dict: bool = True,
    assetsfile: Optional[SerializedFile] = None,
) -> Any:
    """Parse `root_node` from the START of `data` (an object's leading bytes, already read) without
    any reader: same result as read_typetree(..., check_read=False) over a reader positioned at the
    object, but for a caller that fetched the bytes itself. Raises (like the reader-based one) when
    `data` is too short for the node."""
    if data and read_typetree_boost:
        return read_typetree_boost(data, root_node, endian, as_dict, assetsfile, classes)[0]
    reader = EndianBinaryReader(data, endian=endian)
    return read_value(root_node, reader, TypeTreeConfig(as_dict, assetsfile, False))


def write_typetree(
    value: Union[dict[str, Any], Object],
    root_node: TypeTreeNode,
    writer: EndianBinaryWriter,
    assetsfile: Optional[SerializedFile] = None,
) -> None:
    """Writes the typetree of the object contained in the reader via the node list.

    Parameters
    ----------
    value: dict | objects.Object
        The object to be written
    nodes : list
        List of nodes/nodes
    writer : EndianBinaryWriter
        Writer of the object to be parsed
    """
    config = TypeTreeConfig(isinstance(value, dict), assetsfile, False)
    return write_value(value, root_node, writer, config)


def read_value(
    node: TypeTreeNode,
    reader: EndianBinaryReader,
    config: TypeTreeConfig,
) -> Any:
    # print(reader.Position, node.m_Name, node.m_Type, node.m_MetaFlag)
    align = metaflag_is_aligned(node.m_MetaFlag)

    func = FUNCTION_READ_MAP.get(node.m_Type)
    if func:
        value = func(reader)
    elif node.m_Type == "pair":
        first = read_value(node.m_Children[0], reader, config)
        second = read_value(node.m_Children[1], reader, config)
        value = (first, second)
    elif node.m_Type == "ReferencedObject":
        value = {}
        for child in node.m_Children:
            if child.m_Type == "ReferencedObjectData":
                ref_type_nodes = get_ref_type_node(value, config.assetsfile)
                if ref_type_nodes is None:
                    continue
                value[child.m_Name] = read_value(ref_type_nodes, reader, config)
            else:
                value[child.m_Name] = read_value(child, reader, config)
    # Vector
    elif node.m_Children and node.m_Children[0].m_Type == "Array":
        if metaflag_is_aligned(node.m_Children[0].m_MetaFlag):
            align = True

        # size = read_value(node.m_Children[0].m_Children[0], reader, as_dict)
        size = reader.read_int()
        if size < 0:
            raise ValueError("Negative length read from TypeTree")
        subtype = node.m_Children[0].m_Children[1]
        # read_value_array's own FUNCTION_READ_MAP_ARRAY branch is a single bulk
        # struct.unpack call (vs. one Python-level read_value() call per element
        # below) and is safe to use whenever a bulk reader exists for this element
        # type, regardless of whether the element itself carries the align bit —
        # read_value_array recomputes alignment from `subtype.m_MetaFlag` itself
        # and applies it once, after the whole array, exactly like this branch's
        # own `align` (computed from the Array node, above) does. Gating solely on
        # metaflag_is_aligned(subtype.m_MetaFlag) (the historical condition) means
        # plain primitive arrays whose element metaflag happens to not carry the
        # align bit — the common case for e.g. a `vector<UInt8>` byte blob — fall
        # through to the per-element Python loop even though nothing about them
        # requires it: confirmed via profiling this made reading a ~1MB Font
        # m_FontData field (metaflag=1, not aligned) take ~2.2s instead of
        # single-digit ms, and Shader.compressedBlob hits the identical path.
        if metaflag_is_aligned(subtype.m_MetaFlag) or subtype.m_Type in FUNCTION_READ_MAP_ARRAY:
            value = read_value_array(subtype, reader, config, size)
        else:
            value = [read_value(subtype, reader, config) for _ in range(size)]

    else:  # Class
        value = {}
        for child in node.m_Children:
            if child.m_Type == "ManagedReferencesRegistry":
                if config.has_registry:
                    continue
                else:
                    config = config.copy()
                    config.has_registry = True
            value[child.m_Name if config.as_dict else child._clean_name] = read_value(child, reader, config)

        if not config.as_dict:
            if node.m_Type.startswith("PPtr<"):
                value = PPtr[Any](
                    assetsfile=config.assetsfile,
                    m_FileID=value["m_FileID"],
                    m_PathID=value["m_PathID"],
                )
            else:
                clz = getattr(classes, node.m_Type, UnknownObject)
                try:
                    value = clz(**value)
                except TypeError:
                    keys = set(value.keys())
                    annotation_keys = get_annotation_keys(clz)
                    missing_keys = annotation_keys - keys
                    if clz is UnknownObject or missing_keys:
                        value = UnknownObject(node, **value)
                    else:
                        extra_keys = keys - annotation_keys
                        if extra_keys:
                            instance = clz(**{key: value[key] for key in annotation_keys})
                            for key in extra_keys:
                                setattr(instance, key, value[key])
                            value = instance
                        else:
                            value = UnknownObject(**value)

    if align:
        reader.align_stream()

    return value


def read_value_array(
    node: TypeTreeNode,
    reader: EndianBinaryReader,
    config: TypeTreeConfig,
    size: int,
) -> Any:
    align = metaflag_is_aligned(node.m_MetaFlag)

    func = FUNCTION_READ_MAP_ARRAY.get(node.m_Type)
    if func:
        # func (read_u_byte_array/read_int_array/...) returns a tuple
        # (struct.unpack's native return type) — every other branch here, and the
        # per-element loop this fast path replaces at the call site, produces a
        # list. Callers throughout UnityPy rely on that (e.g.
        # export/ShaderConverter.py's get_entry() does `isinstance(item, List)` to
        # detect nesting, which is False for a tuple), so this normalizes back to
        # list. Confirmed via a real before/after diff across several games: this
        # was the one behavioral difference the fast path introduced (verified
        # otherwise byte-for-byte/value-for-value identical) — cheap to convert
        # relative to the per-element Python loop it replaces.
        value = list(func(reader, size))
    elif node.m_Type == "string":
        value = [reader.read_aligned_string() for _ in range(size)]
    elif node.m_Type == "TypelessData":
        value = [reader.read_byte_array() for _ in range(size)]
    elif node.m_Type == "pair":
        key_node = node.m_Children[0]
        value_node = node.m_Children[1]

        key_func = FUNCTION_READ_MAP.get(
            key_node.m_Type,
            lambda reader: read_value(key_node, reader, config),
        )
        value_func = FUNCTION_READ_MAP.get(
            value_node.m_Type,
            lambda reader: read_value(value_node, reader, config),
        )
        value = [(key_func(reader), value_func(reader)) for _ in range(size)]
    elif node.m_Type == "ReferencedObject":
        value = [None] * size
        for i in range(size):
            item = {}
            for child in node.m_Children:
                if child.m_Type == "ReferencedObjectData":
                    ref_type_nodes = get_ref_type_node(item, config.assetsfile)
                    item[child.m_Name] = read_value(ref_type_nodes, reader, config)
                else:
                    item[child.m_Name] = read_value(child, reader, config)
            value[i] = item
    # Vector
    elif node.m_Children and node.m_Children[0].m_Type == "Array":
        if metaflag_is_aligned(node.m_Children[0].m_MetaFlag):
            align = True
        subtype = node.m_Children[0].m_Children[1]
        # Same widened fast-path condition as read_value's Vector branch above —
        # see that comment for why metaflag_is_aligned alone is the wrong gate.
        if metaflag_is_aligned(subtype.m_MetaFlag) or subtype.m_Type in FUNCTION_READ_MAP_ARRAY:
            value = [read_value_array(subtype, reader, config, reader.read_int()) for _ in range(size)]
        else:
            value = [[read_value(subtype, reader, config) for _ in range(reader.read_int())] for _ in range(size)]
    else:  # Class
        if config.as_dict:
            value = [
                {child.m_Name: read_value(child, reader, config) for child in node.m_Children} for _ in range(size)
            ]
        elif node.m_Type.startswith("PPtr<"):
            value = [
                PPtr[Any](
                    assetsfile=config.assetsfile,
                    **{child.m_Name: read_value(child, reader, config) for child in node.m_Children},
                )
                for _ in range(size)
            ]
        else:
            clz = getattr(
                classes,
                node.m_Type,
                UnknownObject,
            )
            keys = set(child._clean_name for child in node.m_Children)
            annotation_keys = get_annotation_keys(clz)
            missing_keys = annotation_keys - keys
            extra_keys = keys - annotation_keys
            if missing_keys or clz is UnknownObject:
                value = [
                    UnknownObject(
                        node,
                        **{child._clean_name: read_value(child, reader, config) for child in node.m_Children},
                    )
                    for _ in range(size)
                ]
            elif extra_keys:
                value = [None] * size
                for i in range(size):
                    value_i_d = {child._clean_name: read_value(child, reader, config) for child in node.m_Children}
                    value_i = clz(**{key: value for key, value in value_i_d.items() if key in annotation_keys})
                    for key in extra_keys:
                        setattr(value_i, key, value_i_d[key])
                    value[i] = value_i
            else:
                value = [
                    clz(**{child._clean_name: read_value(child, reader, config) for child in node.m_Children})
                    for _ in range(size)
                ]

    if align:
        reader.align_stream()
    return value


def metaflag_is_aligned(meta_flag: int | None) -> bool:
    return ((meta_flag or 0) & kAlignBytes) != 0


FUNCTION_WRITE_MAP = {
    "SInt8": EndianBinaryWriter.write_byte,
    "UInt8": EndianBinaryWriter.write_u_byte,
    "char": EndianBinaryWriter.write_u_byte,
    "short": EndianBinaryWriter.write_short,
    "SInt16": EndianBinaryWriter.write_short,
    "unsigned short": EndianBinaryWriter.write_u_short,
    "UInt16": EndianBinaryWriter.write_u_short,
    "int": EndianBinaryWriter.write_int,
    "SInt32": EndianBinaryWriter.write_int,
    "unsigned int": EndianBinaryWriter.write_u_int,
    "UInt32": EndianBinaryWriter.write_u_int,
    "Type*": EndianBinaryWriter.write_u_int,
    "long long": EndianBinaryWriter.write_long,
    "SInt64": EndianBinaryWriter.write_long,
    "unsigned long long": EndianBinaryWriter.write_u_long,
    "UInt64": EndianBinaryWriter.write_u_long,
    "FileSize": EndianBinaryWriter.write_u_long,
    "float": EndianBinaryWriter.write_float,
    "double": EndianBinaryWriter.write_double,
    "bool": EndianBinaryWriter.write_boolean,
    "string": EndianBinaryWriter.write_aligned_string,
    "TypelessData": EndianBinaryWriter.write_byte_array,
}


def write_value(
    value: Union[dict[str, Any], Object],
    node: TypeTreeNode,
    writer: EndianBinaryWriter,
    config: TypeTreeConfig,
) -> None:
    # print(reader.Position, node.m_Name, node.m_Type, node.m_MetaFlag)
    align = metaflag_is_aligned(node.m_MetaFlag)

    func = FUNCTION_WRITE_MAP.get(node.m_Type)
    if func:
        value = func(writer, value)
    elif node.m_Type == "pair":
        write_value(value[0], node.m_Children[0], writer, config)
        write_value(value[1], node.m_Children[1], writer, config)
    elif node.m_Type == "ReferencedObject":
        for child in node.m_Children:
            if child.m_Type == "ReferencedObjectData":
                ref_type_nodes = get_ref_type_node(value, config.assetsfile)
                write_value(value[child.m_Name], ref_type_nodes, writer, config)
            else:
                write_value(value[child.m_Name], child, writer, config)
    elif node.m_Children and node.m_Children[0].m_Type == "Array":
        if metaflag_is_aligned(node.m_Children[0].m_MetaFlag):
            align = True

        writer.write_int(len(value))
        subtype = node.m_Children[0].m_Children[1]
        [write_value(sub_value, subtype, writer, config) for sub_value in value]

    else:  # Class
        if isinstance(value, dict):
            for child in node.m_Children:
                if child.m_Type == "ManagedReferencesRegistry":
                    if config.has_registry:
                        continue
                    else:
                        config = config.copy()
                        config.has_registry = True
                write_value(value[child.m_Name], child, writer, config)
        else:
            for child in node.m_Children:
                if child.m_Type == "ManagedReferencesRegistry":
                    if config.has_registry:
                        continue
                    else:
                        config = config.copy()
                        config.has_registry = True
                write_value(getattr(value, child._clean_name), child, writer, config)

    if align:
        writer.align_stream()
