"""The MonoBehaviour field table (Инструменты -> «Таблица полей MonoBehaviour…», tools/field_table_tool.py): which
fields a script has, and the table rows for the fields the user ticked. No Qt (core/).

Fields come from the script's LAYOUT (its TypeTree node), not from reading objects — so the field list of a script with
thousands of objects is instant ("a quick field scan without full parsing", the user's words); only building the table
reads the objects (`parse_as_dict`). Field paths: `a.b` for nested fields, `a[]` for a list, `a[].b` for a field of the
list's items — the same template form the old field-extractor tool used.

Rows (the user's choice): ONE ROW PER LIST ITEM. An object with 300 `entries[]` gives 300 rows, its other ticked
fields repeated on each; two different lists ticked side by side are paired item by item (row i = item i of each),
nested lists multiply. A list of key/value pairs (a C# Dictionary) gives items with `first` / `second`.

When the layout cannot be generated, UnityPy silently falls back to the bare MonoBehaviour header (m_GameObject,
m_Enabled, m_Script, m_Name) — `script_fields` returns None then, so the tool can say the fields could not be read
instead of offering four header fields as if that were the script."""

from core.i18n import N_, tr
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# The MonoBehaviour header every script object starts with; kept in the tree (m_Name is useful), but a layout that
# has nothing else is the fallback, not the script.
HEADER_FIELDS = ("m_GameObject", "m_Enabled", "m_Script", "m_Name")
# Columns every row of a script's table gets before its ticked fields (the script itself is the table's tab);
# the name first (user request, 2026-10-18).
BASE_COLUMNS = (N_("Имя"), N_("Источник"), "PathID")
# A sample value longer than this is cut in the field tree (the tooltip has the same cut text).
SAMPLE_MAX_LEN = 300
_LIST_TYPES = ("vector", "staticvector", "map", "set")


@dataclass
class FieldNode:
    name: str                    # what the tree shows
    path: str                    # what a ticked field is stored as (see the module docstring)
    type: str
    children: List["FieldNode"] = field(default_factory=list)
    is_list: bool = False


def _array_element(node):
    """The item node of a list field (vector/map/...: <field> -> Array -> [size, data]), else None."""
    if node.m_Type == "string":
        return None
    array = next((c for c in node.m_Children if c.m_Type == "Array"), None)
    if array is not None and len(array.m_Children) >= 2:
        return array.m_Children[1]
    if node.m_Type == "Array" and len(node.m_Children) >= 2:
        return node.m_Children[1]
    return None


def _is_leaf(node) -> bool:
    t = node.m_Type
    return (t == "string" or not node.m_Children or t.startswith("PPtr<") or t in ("TypelessData",))


def _build(node, path: str) -> FieldNode:
    element = _array_element(node)
    if element is not None:
        list_path = f"{path}[]"
        item = FieldNode(node.m_Name, list_path, node.m_Type, is_list=True)
        if not _is_leaf(element) and element.m_Type not in ("UInt8", "char"):
            item.children = [_build(c, f"{list_path}.{c.m_Name}") for c in element.m_Children]
        return item
    if _is_leaf(node):
        return FieldNode(node.m_Name, path, node.m_Type)
    return FieldNode(node.m_Name, path, node.m_Type, [_build(c, f"{path}.{c.m_Name}") for c in node.m_Children])


def script_fields(root_node) -> Optional[List[FieldNode]]:
    """The top-level fields of a script's layout (its TypeTree root), or None when it is only the MonoBehaviour
    header — the layout could not be generated."""
    names = [c.m_Name for c in root_node.m_Children]
    if all(n in HEADER_FIELDS for n in names):
        return None
    return [_build(c, c.m_Name) for c in root_node.m_Children]


def format_value(value) -> str:
    """One cell's text."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return repr(value) if value != int(value) or abs(value) >= 1e16 else str(int(value))
    if isinstance(value, (int, str)):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return tr("<{count} байт>", count=len(value))
    if isinstance(value, dict) and set(value) >= {"m_FileID", "m_PathID"}:     # a reference to another object
        file_id, path_id = value.get("m_FileID", 0), value.get("m_PathID", 0)
        return str(path_id) if not file_id else f"{file_id}:{path_id}"
    try:
        return json.dumps(value, ensure_ascii=False, separators=(", ", ": "), default=str)
    except (TypeError, ValueError):
        return str(value)


_SELF = object()   # marks "this path itself is ticked" inside a selection trie


def _trie(paths: List[str]) -> Dict:
    root: Dict = {}
    for p in paths:
        node = root
        for seg in p.split("."):
            node = node.setdefault(seg, {})
        node[_SELF] = True
    return root


def _as_item(element):
    if isinstance(element, (list, tuple)) and len(element) == 2:         # a Dictionary item: (key, value)
        return {"first": element[0], "second": element[1]}
    return element


def _rows(value, trie: Dict, prefix: str) -> List[Dict[str, str]]:
    base: Dict[str, str] = {}
    lists: List[List[Dict[str, str]]] = []
    for seg, sub in trie.items():
        if seg is _SELF:
            continue
        path = f"{prefix}.{seg}" if prefix else seg
        inner = {k: v for k, v in sub.items() if k is not _SELF}
        if seg.endswith("[]"):
            items = value.get(seg[:-2]) if isinstance(value, dict) else None
            rows: List[Dict[str, str]] = []
            for element in items if isinstance(items, list) else []:
                element = _as_item(element)
                own = {path: format_value(element)} if _SELF in sub else {}
                if inner:
                    rows.extend({**own, **r} for r in _rows(element, inner, path))
                else:
                    rows.append(own)
            lists.append(rows)
        else:
            v = value.get(seg) if isinstance(value, dict) else None
            if _SELF in sub:
                base[path] = format_value(v)
            if inner:
                sub_rows = _rows(v, inner, path)
                if len(sub_rows) == 1:
                    base.update(sub_rows[0])
                else:
                    lists.append(sub_rows)
    if not lists:
        return [base]
    count = max(len(rows) for rows in lists)
    if count == 0:
        return [base]                                    # empty lists: the object still gets its one row
    out = []
    for i in range(count):                               # side-by-side lists are paired item by item
        row = dict(base)
        for rows in lists:
            if i < len(rows):
                row.update(rows[i])
        out.append(row)
    return out


def rows_for_object(data: dict, selected_paths: List[str]) -> List[Dict[str, str]]:
    """Table rows (column path -> cell text) for one parsed object and the ticked paths of its script."""
    if not selected_paths:
        return []
    return _rows(data, _trie(selected_paths), "")


def is_blank(text: str) -> bool:
    """An empty cell, or one holding only spaces/tabs/line breaks."""
    return not text or not text.strip()


# --- what the fields hold (the «Пример» column; the jump from the text search) ---

def _leaf_values(value, nodes: List[FieldNode], max_items: Optional[int], counts: bool = True):
    """(path, cell text) for every leaf value under `nodes` in one parsed object; a list's items in order (at most
    `max_items` of each list, None = all). With `counts`, a list of classes yields «N элем.» for its own path."""
    for node in nodes:
        v = value.get(node.name) if isinstance(value, dict) else None
        if node.is_list:
            if not isinstance(v, list):
                if v is not None:                            # a byte array arrives as bytes
                    yield node.path, format_value(v)
                continue
            if v and counts and node.children:
                yield node.path, tr("{count} элем.", count=len(v))
            items = v if max_items is None else v[:max_items]
            for element in items:
                element = _as_item(element)
                if node.children:
                    yield from _leaf_values(element, node.children, max_items, counts)
                else:
                    yield node.path, format_value(element)
        elif node.children:
            yield from _leaf_values(v, node.children, max_items, counts)
        else:
            yield node.path, format_value(v)


def _leaf_paths(nodes: List[FieldNode]) -> set:
    out = set()
    for node in nodes:
        if node.children:
            out |= _leaf_paths(node.children)
        else:
            out.add(node.path)
    return out


def all_paths(nodes: List[FieldNode]) -> set:
    """Every path of the field tree (lists and classes included)."""
    out = set()
    for node in nodes:
        out.add(node.path)
        out |= all_paths(node.children)
    return out


def sample_values(datas, fields: List[FieldNode], max_items: int = 50) -> Dict[str, str]:
    """{path: the first non-blank value} over the parsed objects `datas` (an iterable — consumed only until every
    leaf has a value). A list field gets its first non-empty item count. Values are cut to SAMPLE_MAX_LEN."""
    leaves = _leaf_paths(fields)
    out: Dict[str, str] = {}
    for data in datas:
        for path, text in _leaf_values(data, fields, max_items):
            if path not in out and not is_blank(text):
                out[path] = text if len(text) <= SAMPLE_MAX_LEN else text[:SAMPLE_MAX_LEN] + "…"
        if leaves <= out.keys():
            break
    return out


def paths_containing(data, fields: List[FieldNode], needle: str) -> List[str]:
    """The leaf paths (tree order) whose value in this object contains `needle` (case-insensitive) — what the text
    search found in it. Every list item is looked at."""
    needle = needle.casefold()
    if not needle:
        return []
    found: List[str] = []
    for path, text in _leaf_values(data, fields, None, counts=False):
        if path not in found and needle in text.casefold():
            found.append(path)
    return found


# --- named sets of ticked fields («Наборы полей»; kept in the app settings as JSON) ---

def parse_presets(text) -> Dict[str, Dict[str, List[str]]]:
    """{preset name: {full script name: [paths in tick order]}}; anything unreadable -> {}."""
    try:
        data = json.loads(text) if text else {}
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for name, scripts in data.items():
        if isinstance(name, str) and isinstance(scripts, dict):
            out[name] = {s: [p for p in paths if isinstance(p, str)]
                         for s, paths in scripts.items() if isinstance(s, str) and isinstance(paths, list)}
    return out


def dump_presets(presets: Dict[str, Dict[str, List[str]]]) -> str:
    return json.dumps(presets, ensure_ascii=False, sort_keys=True)


def match_script(name: str, loaded) -> Optional[str]:
    """The loaded script a preset's script `name` stands for: the same full name, else the only loaded script with
    the same class name (a preset is not tied to one game: TextMeshProUGUI, LeanLocalization… are in many, and a
    namespace can differ between versions of a plugin). None when absent or ambiguous."""
    if name in loaded:
        return name
    bare = name.rsplit(".", 1)[-1]
    same = [s for s in loaded if s.rsplit(".", 1)[-1] == bare]
    return same[0] if len(same) == 1 else None


def resolve_preset(preset: Dict[str, List[str]], loaded, fields_of) -> tuple:
    """A preset against the loaded game -> ({loaded script: the preset's paths that script has}, [preset scripts
    not found], number of fields dropped because the script no longer has them). `loaded` = the loaded full
    script names; `fields_of(script)` = its field tree, or None when unreadable (its paths are then kept)."""
    selections, missing, dropped = {}, [], 0
    for name, paths in preset.items():
        script = match_script(name, loaded)
        if script is None:
            missing.append(name)
            continue
        fields = fields_of(script)
        known = all_paths(fields) if fields is not None else None
        kept = [p for p in paths if known is None or p in known]
        dropped += len(paths) - len(kept)
        if kept:
            selections.setdefault(script, [])
            selections[script] += [p for p in kept if p not in selections[script]]
    return selections, missing, dropped
