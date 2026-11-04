"""What an object refers to — the «Сведения» tab's «Ссылается на» list (no Qt).

Every non-empty reference (PPtr) in the object's fields, with the field it sits in ("m_Materials[0]",
"m_Component[2].component") and the object it points to. Resolved ONLY among the files that are already loaded:
UnityPy's PPtr.deref() falls back to Environment.find_file(), which may search the disk and load another file —
fine for one reference the user expands in the tree, not for every reference of every selected object. A reference
into a file that is not loaded is listed with that file's name and «файл не загружен».

Built from the same parsed (data, node) pair the preview already made (core/object_preview.build_preview), so it
costs a walk over that dict plus a lookup per reference, never another parse of the object."""

from __future__ import annotations

from core.i18n import N_, tr
import weakref
from dataclasses import dataclass
from typing import List, Tuple

from .object_common import _PRIMITIVE_TYPES, resolve_object_name, resolve_script_name

# The list stops here: a MonoBehaviour can hold thousands of references (a lookup table of sprites); the count
# says how many there are in all.
MAX_REFERENCES = 500

UNLOADED = N_("файл не загружен")
MISSING = N_("объект не найден")
# The object exists, but its type was left out of the load (the loading settings choose which types are read —
# by default Transform, renderers, MeshFilter... are not). Its type comes from the file's own object table.
TYPE_NOT_LOADED = N_("тип не загружен")

# file -> (sorted path ids, class ids in that order); weak, so a closed game's files are never kept alive by it
_excluded_index: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _excluded_type(target_file, path_id: int) -> str:
    """The type name of an object the load skipped (SerializedFile._excluded_objects), or ""."""
    records = getattr(target_file, "_excluded_objects", None)
    if records is None or not len(records):
        return ""
    import numpy as np
    try:
        cached = _excluded_index.get(target_file)
    except TypeError:                               # not weak-referenceable: no cache, still correct
        cached = None
    if cached is None or cached[0] is not records:     # an adopted object leaves the file's records (a new array)
        order = np.argsort(records["path_id"], kind="stable")
        cached = (records, records["path_id"][order], records["class_id"][order])
        try:
            _excluded_index[target_file] = cached
        except TypeError:
            pass
    _records, ids, classes = cached
    i = int(np.searchsorted(ids, path_id))
    if i >= len(ids) or int(ids[i]) != path_id:
        return ""
    try:
        from UnityPy.enums import ClassIDType
        return ClassIDType(int(classes[i])).name
    except Exception:
        return tr("класс {id}", id=int(classes[i]))


@dataclass
class Reference:
    field: str                 # where in the object: "m_Materials[0]", "m_Component[2].component"
    type_name: str             # the target's type (or, unresolved, the type the reference declares)
    name: str = ""             # the target's display name; for a MonoBehaviour also its script, see `script`
    script: str = ""
    file_name: str = ""        # the file the target lives in (or should: see `problem`)
    path_id: int = 0
    target: object = None      # the ObjectReader, or None
    problem: str = ""          # why there is no target, in plain words
    # A target that is there but not in the table: an object whose type the load left out (TYPE_NOT_LOADED). It is
    # read through SerializedFile.skipped_object() — it opens, jumps and can be edited (its first edit adopts it).
    note: str = ""
    # How many fields `field` names (", "-joined): the lists show one row per OBJECT — a Material holding the same
    # texture in _BaseMap and _MainTex is one row with both fields (user report: «Используется в · 4» for 2 materials).
    field_count: int = 1


@dataclass
class ObjectFacts:
    type_name: str
    name: str
    path_id: int
    file_name: str             # the loaded file holding the object (inside a bundle: the bundle's entry)
    source: str                # the file on disk it came from (a bundle's own file name), when different
    container: str             # the asset path (`m_Container`), when the object has one
    byte_size: int
    script: str = ""


def object_facts(obj) -> ObjectFacts:
    """The plain facts the «Сведения» tab opens with. Cheap: no parse."""
    assets_file = getattr(obj, "assets_file", None)
    file_name = getattr(assets_file, "name", "") or ""
    source = ""
    root = assets_file
    while getattr(root, "parent", None) is not None and hasattr(root.parent, "files") and hasattr(root.parent, "name"):
        root = root.parent
    if root is not assets_file:
        source = getattr(root, "name", "") or ""
    try:
        container = obj.container or ""
    except Exception:
        container = ""
    type_name = obj.type.name
    script = ""
    if type_name == "MonoBehaviour":
        try:
            script = resolve_script_name(obj)
        except Exception:
            script = ""
    try:
        name = resolve_object_name(obj)
    except Exception:
        name = ""
    return ObjectFacts(type_name=type_name, name=name, path_id=obj.path_id, file_name=file_name, source=source,
                       container=container, byte_size=getattr(obj, "byte_size", 0) or 0, script=script)


# ---------------------------------------------------------------- collecting

def _collect(node, value, path: str, out: list) -> None:
    """(field path, declared type, file id, path id) of every non-empty PPtr below `node`, walking the schema next
    to the parsed value (as the structure tree and the Dump tab do)."""
    t = node.m_Type
    if t in _PRIMITIVE_TYPES or t == "TypelessData":
        return
    children = node.m_Children
    if children and children[0].m_Type == "Array":
        if not isinstance(value, (list, tuple)) or len(children[0].m_Children) < 2:
            return
        sub = children[0].m_Children[1]
        if sub.m_Type in _PRIMITIVE_TYPES:
            return                                    # byte/int arrays: nothing to find, and they can be huge
        if sub.m_Type == "pair" and len(sub.m_Children) == 2:
            for i, item in enumerate(value):
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    if isinstance(item[0], str):
                        # a map with text keys (a material's m_TexEnvs): the key names the entry —
                        # "m_TexEnvs[_MainTex].m_Texture" rather than "m_TexEnvs[0].second.m_Texture"
                        _collect(sub.m_Children[1], item[1], f"{path}[{item[0]}]", out)
                    else:
                        _collect(sub.m_Children[0], item[0], f"{path}[{i}].first", out)
                        _collect(sub.m_Children[1], item[1], f"{path}[{i}].second", out)
            return
        for i, item in enumerate(value):
            _collect(sub, item, f"{path}[{i}]", out)
        return
    if t.startswith("PPtr<"):
        if isinstance(value, dict) and value.get("m_PathID"):
            out.append((path, t[5:-1], int(value.get("m_FileID", 0) or 0), int(value["m_PathID"])))
        return
    if isinstance(value, dict):
        for child in children:
            _collect(child, value.get(child.m_Name), f"{path}.{child.m_Name}" if path else child.m_Name, out)


# ---------------------------------------------------------------- resolving

def _external_name(assets_file, file_id: int) -> str:
    externals = getattr(assets_file, "externals", None) or []
    if 0 < file_id <= len(externals):
        return externals[file_id - 1].path
    return ""


def _clean(path: str) -> str:
    """The lookup name PPtr.deref() derives from an external path (same steps)."""
    if path.startswith("archive:/"):
        path = path[9:]
    if path.startswith("assets/"):
        path = path[7:]
    return path.rsplit("/")[-1].lower()


def _loaded_file(assets_file, file_id: int):
    """The already-loaded file a reference's file id points to, or None — PPtr.deref()'s lookup without its
    find_file() fallback (which may load a file from disk)."""
    if file_id == 0:
        return assets_file
    external = _external_name(assets_file, file_id)
    if not external:
        return None
    name = _clean(external)
    container = getattr(assets_file, "parent", None)
    env = getattr(assets_file, "environment", None)
    if container is not None and container is not env and hasattr(container, "files"):
        for key, file in container.files.items():
            if key.lower() == name and hasattr(file, "objects"):
                return file
    if env is not None:
        try:
            found = env.get_cab_near(name, assets_file) if hasattr(env, "get_cab_near") else env.get_cab(name)
        except Exception:
            found = None
        if found is not None and hasattr(found, "objects"):
            return found
    return None


def _describe_target(ref: Reference, target) -> None:
    ref.target = target
    ref.type_name = target.type.name
    try:
        ref.name = resolve_object_name(target)
    except Exception:
        ref.name = ""
    if ref.type_name == "MonoBehaviour":
        try:
            ref.script = resolve_script_name(target)
        except Exception:
            ref.script = ""


def incoming_references(users, limit: int = MAX_REFERENCES) -> Tuple[List[Reference], int]:
    """Rows for «Используется в»: the usage index's [(source object, field)] described like «Ссылается на» rows
    (target = the referring object, field = where in IT the reference sits). One row per referring object, with
    every field it refers from; the count is of objects."""
    grouped: dict = {}
    for source, field in users:
        key = (id(source.assets_file), source.path_id)
        entry = grouped.get(key)
        if entry is None:
            grouped[key] = (source, [field])
        elif field not in entry[1]:
            entry[1].append(field)
    rows: List[Reference] = []
    for source, fields in list(grouped.values())[:limit]:
        ref = Reference(field=", ".join(fields), type_name=source.type.name, path_id=source.path_id,
                        file_name=getattr(source.assets_file, "name", "") or "", field_count=len(fields))
        _describe_target(ref, source)
        rows.append(ref)
    return rows, len(grouped)


def merge_same_targets(refs: List[Reference], total: int) -> Tuple[List[Reference], int]:
    """«Ссылается на» rows of outgoing_references() merged to one per target object (its fields joined), and the
    total less the rows merged away. A reference with no target merges with another to the same file and PathID."""
    merged: dict = {}
    for ref in refs:
        key = (("obj", id(ref.target.assets_file), ref.target.path_id) if ref.target is not None
               else ("missing", ref.file_name, ref.path_id))
        first = merged.get(key)
        if first is None:
            merged[key] = ref
        elif ref.field not in first.field.split(", "):
            first.field = f"{first.field}, {ref.field}"
            first.field_count += 1
    rows = list(merged.values())
    return rows, total - (len(refs) - len(rows))


def outgoing_references(obj, data, node, limit: int = MAX_REFERENCES) -> Tuple[List[Reference], int]:
    """(the first `limit` references of `obj`, how many it has in all). `data`/`node` are its parsed dict and
    type tree root (None: nothing to walk, empty list)."""
    if data is None or node is None:
        return [], 0
    found: list = []
    for child in node.m_Children:
        _collect(child, data.get(child.m_Name) if isinstance(data, dict) else None, child.m_Name, found)
    assets_file = obj.assets_file
    refs: List[Reference] = []
    files: dict = {}
    for field, declared, file_id, path_id in found[:limit]:
        if file_id not in files:
            files[file_id] = _loaded_file(assets_file, file_id)
        target_file = files[file_id]
        ref = Reference(field=field, type_name=declared, path_id=path_id)
        ref.file_name = (getattr(assets_file, "name", "") if file_id == 0
                         else (_clean(_external_name(assets_file, file_id)) or f"FileID {file_id}"))
        target = None
        if target_file is None:
            ref.problem = tr(UNLOADED)
        else:
            target = target_file.objects.get(path_id)
            ref.file_name = getattr(target_file, "name", "") or ref.file_name
            if target is None:
                skipped = _excluded_type(target_file, path_id)
                if skipped:
                    ref.type_name = skipped
                    try:
                        target = target_file.skipped_object(path_id)
                    except Exception:
                        target = None
                    if target is not None:
                        ref.note = tr(TYPE_NOT_LOADED)
                    else:
                        ref.problem = tr(TYPE_NOT_LOADED)
                else:
                    ref.problem = tr(MISSING)
        if target is not None:
            _describe_target(ref, target)
        refs.append(ref)
    return refs, len(found)
