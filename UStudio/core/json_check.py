"""Does a JSON dump fit the object it is about to be written into?

JSON import (core.object_import.import_object_json) hands the file's dict to obj.patch(), which writes it
through the object's OWN type schema: a field the schema has and the file lacks fails with a bare KeyError,
a field the file has and the schema lacks is silently dropped, and a dump of another script with the same
fields is written without a word - leaving the object pointing at the other script (m_Script is one of the
fields). Patch files are matched to objects by (file, PathID) and a filename check on the script's CLASS
name only, which can be "Unknown" (the script did not resolve when the dump was exported) or ambiguous
(Kindergarten 3 has PixelCrushers.DialogueSystem.DialogueSystemTrigger and
PixelCrushers.DialogueSystem.Wrappers.DialogueSystemTrigger). So before writing, the dump itself is checked:

1. MonoBehaviour identity: the dump's m_Script pointer must be the object's own (the same rule as Raw
   import, core/raw_check.py).
2. Structure: every level of the dump has exactly the fields the schema has there, and each value is of
   the kind the schema writes (a group, a list, text, a number).

PyQt-free; shared by the GUI's and the CLI's JSON import. Never raises: a check that cannot run lets the
data through (the write itself still fails on what it cannot write)."""

from core.i18n import N_, tr
import logging
from typing import Any, List, Optional

from .raw_check import SCRIPT_MESSAGE

logger = logging.getLogger(__name__)

_INT_TYPES = frozenset({
    "SInt8", "UInt8", "char", "short", "SInt16", "unsigned short", "UInt16", "int", "SInt32",
    "unsigned int", "UInt32", "Type*", "long long", "SInt64", "unsigned long long", "UInt64", "FileSize",
})
_FLOAT_TYPES = frozenset({"float", "double"})
# Their content depends on data elsewhere (the type each managed reference names): not checked inside.
_OPEN_TYPES = frozenset({"ReferencedObject", "ReferencedObjectData", "ManagedReferencesRegistry"})
_MAX_REPORTED_FIELDS = 3
# The Python types a list item of a primitive node may have (what _check accepts for one value).
_LEAF_KINDS = {**{t: {int, bool} for t in _INT_TYPES | {"bool"}},
               **{t: {int, bool, float} for t in _FLOAT_TYPES}, "string": {str}}

SAME_NAMES_MESSAGE = (
    N_("У этого объекта есть поля с одинаковыми именами, и в JSON их не различить, поэтому импорт из JSON "
    "невозможен. Используйте Raw-импорт (.dump.bin). Объект не изменён.")
)


class _Mismatch(Exception):
    def __init__(self, kind: str, path: str):
        super().__init__(path)
        self.kind = kind   # "missing" | "extra" | "kind" | "same_names"
        self.path = path


def _join(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name


def _check(value: Any, node, path: str, problems: List[_Mismatch]) -> None:
    node_type = node.m_Type
    if node_type in _OPEN_TYPES:
        return
    if node_type in _INT_TYPES or node_type == "bool":
        if isinstance(value, int):   # bool is an int too
            return
        raise _Mismatch("kind", path)
    if node_type in _FLOAT_TYPES:
        if isinstance(value, (int, float)):
            return
        raise _Mismatch("kind", path)
    if node_type == "string":
        if isinstance(value, str):
            return
        raise _Mismatch("kind", path)
    if node_type == "TypelessData":
        if isinstance(value, (bytes, bytearray, list)):
            return
        raise _Mismatch("kind", path)
    if node_type == "pair":
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise _Mismatch("kind", path)
        _check(value[0], node.m_Children[0], f"{path}[0]", problems)
        _check(value[1], node.m_Children[1], f"{path}[1]", problems)
        return
    children = node.m_Children
    if children and children[0].m_Type == "Array":
        if isinstance(value, (bytes, bytearray)):
            return
        if not isinstance(value, (list, tuple)):
            raise _Mismatch("kind", path)
        item_node = children[0].m_Children[1]
        allowed = _LEAF_KINDS.get(item_node.m_Type)
        if allowed is not None and set(map(type, value)) <= allowed:
            return   # a big list of numbers (a font's 30 M bytes): one pass in C instead of a call per item
        for i, item in enumerate(value):
            _check(item, item_node, f"{path}[{i}]", problems)
        return
    if not isinstance(value, dict):
        raise _Mismatch("kind", path)
    names = [child.m_Name for child in children]
    if len(set(names)) != len(names):
        # Obfuscated scripts (Knock-knock: a dozen fields all named "?"): a JSON object keeps one value per
        # name, so such fields cannot be told apart in a dump at all.
        raise _Mismatch("same_names", path)
    expected = set()
    for child in children:
        if child.m_Type == "ManagedReferencesRegistry":
            expected.add(child.m_Name)   # present or not (a nested one is not written), never checked inside
            continue
        expected.add(child.m_Name)
        if child.m_Name not in value:
            problems.append(_Mismatch("missing", _join(path, child.m_Name)))
            continue
        _check(value[child.m_Name], child, _join(path, child.m_Name), problems)
    for key in value:
        if key not in expected:
            problems.append(_Mismatch("extra", _join(path, key)))


def structure_problems(data: dict, node) -> List[_Mismatch]:
    """Every place where `data` does not fit `node` (a field missing or extra at some level, or a value of
    another kind - which stops the walk under that value)."""
    problems: List[_Mismatch] = []
    try:
        _check(data, node, "", problems)
    except _Mismatch as e:
        problems.append(e)
    return problems


def _describe(problems: List[_Mismatch]) -> str:
    def names(kind):
        found = [f"«{p.path}»" for p in problems if p.kind == kind]
        text = ", ".join(found[:_MAX_REPORTED_FIELDS])
        if len(found) > _MAX_REPORTED_FIELDS:
            text += " " + tr("и ещё {count}", count=len(found) - _MAX_REPORTED_FIELDS)
        return text
    parts = []
    if names("missing"):
        parts.append(tr("в файле нет полей объекта: {names}", names=names('missing')))
    if names("extra"):
        parts.append(tr("в файле есть поля, которых у объекта нет: {names}", names=names('extra')))
    if names("kind"):
        parts.append(tr("не того вида значение: {names}", names=names('kind')))
    return "; ".join(parts)


def _pointer(value) -> Optional[tuple]:
    if isinstance(value, dict):
        file_id, path_id = value.get("m_FileID"), value.get("m_PathID")
    else:
        file_id, path_id = getattr(value, "m_FileID", None), getattr(value, "m_PathID", None)
    if isinstance(file_id, int) and isinstance(path_id, int):
        return file_id, path_id
    return None


def _script_problem(obj, data: dict) -> Optional[str]:
    declared = _pointer(data.get("m_Script"))
    if declared is None:
        return None   # no pointer in the file: the structure check reports it
    try:
        current = _pointer((obj.peek_dict(("m_Script",)) or {}).get("m_Script"))
    except Exception:
        return None
    if current is not None and current != declared:
        return tr(SCRIPT_MESSAGE)
    return None


def json_replacement_problem(obj, data: dict) -> Optional[str]:
    """None when `data` (an already restored JSON dump) may be written into obj, else a complete,
    user-facing reason - the object is not touched in that case."""
    try:
        type_name = getattr(obj.type, "name", "") or tr("объект")
        if type_name == "MonoBehaviour":
            problem = _script_problem(obj, data)
            if problem:
                return problem
        try:
            node = obj._get_typetree_node()
        except Exception:
            return None
        problems = structure_problems(data, node)
        if not problems:
            return None
        if any(p.kind == "same_names" for p in problems):
            return tr(SAME_NAMES_MESSAGE)
        made_for = tr("для другого скрипта") if type_name == "MonoBehaviour" else tr("для другого объекта")
        return (
            tr("Данные не подходят к этому объекту ({type_name}): {describe}. Файл сделан {made_for} или для "
               "другой версии игры. Объект не изменён.", type_name=type_name, describe=_describe(problems), made_for=made_for)
        )
    except Exception:
        logger.debug("JSON structure check could not run", exc_info=True)
        return None
