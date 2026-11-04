"""The loaded game as a tree of files — what the «Окружение» tab shows (no Qt).

Folders (relative to the folder all loaded files share) -> the files the load opened (env.files) -> what a bundle /
web file holds (its CABs, .resS, nested bundles). Built from data UnityPy already has in memory: nothing is read
from disk except a top-level file's size (os.stat). A node holds a reference to its UnityPy file, so the caller must
drop the whole tree before the game's files are closed (MainWindow does it next to the usage index).

`file_facts(node)` gives the («Label», "value") pairs shown under the tree; `serialized_files(node)` is every
SerializedFile at or under a node (what «Показать объекты» / «Экспортировать все объекты» act on)."""
from core.i18n import N_, tr
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional

from UnityPy.files.BundleFile import BundleFile
from UnityPy.files.SerializedFile import SerializedFile
from UnityPy.files.WebFile import WebFile

FOLDER, BUNDLE, WEB, SERIALIZED, RESOURCE, OTHER = "folder", "bundle", "web", "serialized", "resource", "other"

KIND_TEXT = {
    FOLDER: N_("Папка"),
    BUNDLE: N_("Архив (бандл)"),
    WEB: N_("Веб-архив"),
    SERIALIZED: N_("Файл ассетов"),
    RESOURCE: N_("Данные ресурсов"),
    OTHER: N_("Файл"),
}


@dataclass(eq=False)
class EnvNode:
    name: str
    kind: str
    item: object = None             # the UnityPy file (None for a folder)
    path: Optional[str] = None      # physical path: a folder, or a file the load opened itself
    children: List["EnvNode"] = field(default_factory=list)
    parent: Optional["EnvNode"] = None

    @property
    def is_container(self) -> bool:
        return bool(self.children) or self.kind in (FOLDER, BUNDLE, WEB)

    def is_changed(self) -> bool:
        if self.kind == FOLDER:
            return any(c.is_changed() for c in self.children)
        return bool(getattr(self.item, "is_changed", False))

    def is_dependency(self) -> bool:
        return bool(getattr(self.item, "is_dependency", False))


def kind_of(item, name: str = "") -> str:
    """`name`: the file's own name (a raw reader — .resS, .txt — has none of its own)."""
    if isinstance(item, SerializedFile):
        return SERIALIZED
    if isinstance(item, BundleFile):
        return BUNDLE
    if isinstance(item, WebFile):
        return WEB
    name = (name or getattr(item, "name", "") or "").lower()
    if name.endswith((".ress", ".resource")):
        return RESOURCE
    return OTHER            # a loose non-Unity file the folder load picked up (.txt, .json, app.info, ...)


def _sort_key(node: EnvNode):
    """Folders first, then by name with numbers compared as numbers (level2 before level10)."""
    parts = re.split(r"(\d+)", node.name.lower())
    return (0 if node.kind == FOLDER else 1, [int(p) if p.isdigit() else p for p in parts])


def _inner_nodes(item, parent: EnvNode) -> List[EnvNode]:
    files = getattr(item, "files", None)
    if not isinstance(files, dict) or isinstance(item, SerializedFile):
        return []
    nodes = []
    for name, sub in files.items():
        node = EnvNode(os.path.basename(str(name)) or str(name), kind_of(sub, str(name)), sub, parent=parent)
        node.children = _inner_nodes(sub, node)
        nodes.append(node)
    nodes.sort(key=_sort_key)
    return nodes


def build_tree(env) -> List[EnvNode]:
    """Root nodes for env: the shared folder's own subfolders and files (a single shared folder is one root node,
    so the game's data folder shows as the top). Files whose key is not a real path (opened from memory) go under
    «(в памяти)»."""
    files = dict(getattr(env, "files", None) or {})
    on_disk = {k: v for k, v in files.items() if isinstance(k, str) and os.path.isabs(k)}
    in_memory = {k: v for k, v in files.items() if k not in on_disk}
    roots: List[EnvNode] = []
    if on_disk:
        dirs = [os.path.dirname(os.path.normpath(k)) for k in on_disk]
        try:
            base = os.path.commonpath(dirs)
        except ValueError:          # different drives
            base = ""
        top = EnvNode(os.path.basename(base) or base or "?", FOLDER, path=base or None) if base else None
        folders = {}

        def folder_for(rel_dir: str, root_node: Optional[EnvNode], root_path: str) -> Optional[EnvNode]:
            if rel_dir in ("", "."):
                return root_node
            if rel_dir in folders:
                return folders[rel_dir]
            parent_rel, name = os.path.split(rel_dir)
            parent = folder_for(parent_rel, root_node, root_path)
            node = EnvNode(name, FOLDER, path=os.path.join(root_path, rel_dir), parent=parent)
            (parent.children if parent is not None else roots).append(node)
            folders[rel_dir] = node
            return node

        for key, item in on_disk.items():
            norm = os.path.normpath(key)
            if base:
                parent = folder_for(os.path.relpath(os.path.dirname(norm), base), top, base)
            else:
                drive_dir = os.path.dirname(norm)
                parent = folders.get(drive_dir)
                if parent is None:
                    parent = folders[drive_dir] = EnvNode(drive_dir, FOLDER, path=drive_dir)
                    roots.append(parent)
            node = EnvNode(os.path.basename(norm), kind_of(item, norm), item, path=norm, parent=parent)
            node.children = _inner_nodes(item, node)
            (parent.children if parent is not None else roots).append(node)
        if top is not None:
            roots.insert(0, top)
    if in_memory:
        mem = EnvNode(tr("(в памяти)"), FOLDER)
        for key, item in in_memory.items():
            node = EnvNode(os.path.basename(str(key)) or str(key), kind_of(item, str(key)), item, parent=mem)
            node.children = _inner_nodes(item, node)
            mem.children.append(node)
        roots.append(mem)
    _sort_all(roots)
    return roots


def _sort_all(nodes: List[EnvNode]) -> None:
    nodes.sort(key=_sort_key)
    for n in nodes:
        if n.kind == FOLDER:
            _sort_all(n.children)


def walk(nodes):
    for n in nodes:
        yield n
        yield from walk(n.children)


def serialized_files(node: EnvNode) -> List[SerializedFile]:
    """Every SerializedFile at or under `node` (itself for a SerializedFile)."""
    return [n.item for n in walk([node]) if n.kind == SERIALIZED]


def container_path(node: EnvNode) -> Optional[str]:
    """The physical file a node lives in: its own path, or the nearest ancestor's."""
    while node is not None:
        if node.path:
            return node.path
        node = node.parent
    return None


def _size_text(n: int) -> str:
    from helpers import format_size
    return format_size(n)


def _compression(bundle) -> str:
    flags = getattr(bundle, "_block_info_flags", None)
    if flags is None:
        return ""
    from UnityPy.enums import CompressionFlags
    try:
        comp = CompressionFlags(int(flags) & 0x3F)
    except ValueError:
        return tr("неизвестное ({id})", id=int(flags) & 0x3F)
    return {"NONE": tr("без сжатия"), "LZMA": "LZMA", "LZ4": "LZ4", "LZ4HC": "LZ4HC", "LZHAM": "LZHAM"}.get(comp.name, comp.name)


def common_versions(roots) -> tuple:
    """(Unity version, platform name) most of the game's asset files have — what file_facts leaves out."""
    versions, platforms = Counter(), Counter()
    for n in walk(roots):
        if n.kind == SERIALIZED:
            versions[getattr(n.item, "unity_version", "")] += 1
            platforms[getattr(getattr(n.item, "target_platform", None), "name", "")] += 1
    top = lambda c: c.most_common(1)[0][0] if c else ""      # noqa: E731
    return top(versions), top(platforms)


def file_facts(node: EnvNode, common: tuple = ("", "")) -> List[tuple]:
    """(«Label», value) pairs for the facts box. Cheap: in-memory attributes and one os.stat(). The Unity version
    and platform appear only where they differ from `common` (common_versions: the rest of the game's) — the same
    value on every file is noise (user request), a different one is worth seeing («unity default resources» of
    Kindergarten 3 is 2022.3.2f1 / StandaloneWindows in a 2022.3.5f1 / Windows64 game). What the tree already
    shows (how many files a bundle holds) is left out too."""
    facts = [(tr("Тип"), tr(KIND_TEXT[node.kind]) if node.kind in KIND_TEXT else node.kind)]
    item = node.item
    if node.kind == FOLDER:
        if node.path:
            facts.append((tr("Путь"), node.path))
        return facts
    if node.path:
        facts.append((tr("Путь"), node.path))
        try:
            facts.append((tr("Размер на диске"), _size_text(os.path.getsize(node.path))))
        except OSError:
            pass
    else:
        outer = container_path(node)
        if outer:
            facts.append((tr("В архиве"), outer))
    if node.kind in (BUNDLE, WEB):
        signature = getattr(item, "signature", "")
        if signature:
            facts.append((tr("Формат"), signature))
        engine = getattr(item, "version_engine", "")
        if engine and engine != common[0]:
            facts.append((tr("Версия Unity"), engine))
        comp = _compression(item) if node.kind == BUNDLE else ""
        if comp:
            facts.append((tr("Сжатие"), comp))
    elif node.kind == SERIALIZED:
        version = getattr(item, "unity_version", "")
        if version and version != common[0]:
            facts.append((tr("Версия Unity"), version))
        platform = getattr(getattr(item, "target_platform", None), "name", "")
        if platform and platform != common[1]:
            facts.append((tr("Платформа"), platform))
        facts.append((tr("Объектов загружено"), str(len(getattr(item, "objects", {}) or {}))))
        excluded = getattr(item, "_excluded_objects", None)
        if excluded is not None and len(excluded):
            facts.append((tr("Пропущено при загрузке"), str(len(excluded))))
        if not node.path:
            length = getattr(getattr(item, "reader", None), "Length", None)
            if length:
                facts.append((tr("Размер"), _size_text(int(length))))
    elif node.kind in (RESOURCE, OTHER) and not node.path:
        length = getattr(item, "Length", None)
        if length:
            facts.append((tr("Размер"), _size_text(int(length))))
    if node.is_dependency():
        facts.append((tr("Загружен"), tr("только для ссылок других файлов")))
    if node.is_changed():
        facts.append((tr("Изменён"), tr("да — изменения ещё не сохранены")))
    return facts
