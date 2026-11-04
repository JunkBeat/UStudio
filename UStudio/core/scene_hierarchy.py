"""Builds the GameObject/Transform hierarchy for the Scene Viewer tool
(Tools -> Просмотр сцены, aka the "GameObject Viewer" per the UABEA reference
this was modeled on). PyQt-free, matching core/object_preview.py's own
convention — no GUI dependency, just UnityPy reads.

A Unity scene's hierarchy isn't stored as its own structure — it's implicit in
every Transform/RectTransform object's own m_Father/m_Children PPtr fields.
This walks all Transform-family objects in ONE SerializedFile, resolves each
one's owning GameObject (for display name + the component list the Scene
Viewer's right pane shows), and links parent/child via m_Children (not
m_Father — see build_scene_hierarchy's own docstring for why).

Built eagerly, not lazily like gui_widgets.ObjectStructureTree: a scene's
GameObject count is normally a small fraction of a file's total object count
(a level with tens of millions of objects still typically has GameObjects only
in the thousands-to-low-hundred-thousands range), so a single upfront pass is
the same tradeoff UABEA's own GameObject Viewer makes. A real report (Truck-kun,
level3 = 88k Transforms, ~4 s per open) showed it is not always small: the pass
now runs in the Scene Viewer's background worker (cancellable, with progress),
the viewer keeps what it built, and its tree creates rows only when expanded.
"""

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from UnityPy.classes.PPtr import PPtr

from .progress import OperationCancelled, Pacer

_TRANSFORM_TYPES = ("Transform", "RectTransform")
_TRANSFORM_FIELDS = ("m_GameObject", "m_Children")


@dataclass(slots=True)
class SceneNode:
    """One GameObject's place in the hierarchy. `game_object_obj` is the
    resolved GameObject ObjectReader (None only if its PPtr didn't resolve —
    shown with a fallback name in that case, never dropped from the tree,
    since the Transform itself still legitimately exists). slots: a big
    scene has ~90k of these (Truck-kun level3), and the Scene Viewer keeps
    the hierarchies it built."""
    name: str
    transform_obj: object
    game_object_obj: Optional[object]
    children: List["SceneNode"] = field(default_factory=list)


_CHECK_EVERY = 250        # objects between cancel checks / pacing (~2-4 ms of reading)
# Pacing for a build in a background thread (`paced=True`): core.progress.Pacer, as every background pass — a Python
# thread that never sleeps keeps the GUI thread waiting for the GIL (the window froze up to ~1.7 s while
# Truck-kun's level3 was being built).


def _path_id_of(ptr) -> int:
    if isinstance(ptr, dict):
        return ptr.get("m_PathID") or 0
    return getattr(ptr, "path_id", 0) or getattr(ptr, "m_PathID", 0) or 0


def _gameobject_name(go_obj) -> Optional[str]:
    name = go_obj.peek_name()  # bounded read: only m_Name, not the component list after it
    if name is None:
        name = go_obj.parse_as_dict().get("m_Name")
    return name


def build_scene_hierarchy(assets_file, should_cancel: Optional[Callable[[], bool]] = None,
                          progress: Optional[Callable[[int, int], None]] = None,
                          paced: bool = False) -> List[SceneNode]:
    """Returns the list of ROOT SceneNodes (top-level GameObjects with no
    parent within this same file) for `assets_file` — everything else hangs
    off their `.children`, in the same order Unity itself stores each
    Transform's own m_Children array (real sibling order, not object-table/
    path_id order).

    Root detection: a Transform is a root if it's never referenced as a CHILD
    by any other Transform in this same file — computed from the m_Children
    arrays already being walked anyway, rather than resolving each one's own
    m_Father PPtr (which could point cross-file for a prefab-like reference;
    treating that case as "a root of THIS file's hierarchy view" is the
    correct, expected behavior for a per-file scene viewer, matching the
    reference tool's own per-file scoping).

    Reads only what it shows: a Transform's m_GameObject + m_Children and the GameObject's m_Name
    (bounded reads), not both objects in full — level3 of Truck-kun (88k Transforms) 1.25 -> ~0.8 s.
    Runs in the Scene Viewer's background worker: `should_cancel` is polled every 250 objects (raises
    OperationCancelled), `progress(done, total)` is called as often (done counts both passes: 2 x the
    Transforms), and `paced` rests the thread regularly (see WORK_SLICE_S)."""
    candidates = [obj for obj in assets_file.objects.values() if obj.type.name in _TRANSFORM_TYPES]
    total = 2 * len(candidates)
    pacer = Pacer() if paced else None

    def checkpoint(done: int) -> None:
        if should_cancel is not None and should_cancel():
            raise OperationCancelled()
        if progress is not None:
            progress(done, total)
        if pacer is not None:
            pacer.step()

    transforms = {}
    for i, obj in enumerate(candidates):
        if i % _CHECK_EVERY == 0:
            checkpoint(i)
        try:
            d = obj.peek_dict(_TRANSFORM_FIELDS)
        except Exception:
            continue
        if d is None:
            continue
        transforms[obj.path_id] = (obj, d)

    nodes = {}
    for i, (path_id, (obj, d)) in enumerate(transforms.items()):
        if i % _CHECK_EVERY == 0:
            checkpoint(len(candidates) + i)
        go_obj = None
        go_name = f"<{obj.type.name}>"
        go_ptr = d.get("m_GameObject")
        go_path_id = _path_id_of(go_ptr)
        if go_path_id:
            try:
                go_obj = PPtr(
                    m_FileID=(go_ptr.get("m_FileID", 0) if isinstance(go_ptr, dict)
                              else getattr(go_ptr, "file_id", 0)),
                    m_PathID=go_path_id,
                    assetsfile=obj.assets_file,
                ).deref()
                go_name = _gameobject_name(go_obj) or go_name
            except Exception:
                pass
        nodes[path_id] = SceneNode(name=go_name, transform_obj=obj, game_object_obj=go_obj)

    child_path_ids = set()
    for path_id, (obj, d) in transforms.items():
        node = nodes[path_id]
        for child_ptr in d.get("m_Children") or []:
            child_node = nodes.get(_path_id_of(child_ptr))
            if child_node is not None:
                node.children.append(child_node)
                child_path_ids.add(_path_id_of(child_ptr))
    if progress is not None:
        progress(total, total)

    return [nodes[pid] for pid in transforms if pid not in child_path_ids]


def resolve_gameobject_components(game_object_obj) -> List[object]:
    """Resolves a GameObject's own m_Component array (one PPtr<Component> per
    entry, e.g. Transform/MonoBehaviour/MeshRenderer/...) into the actual
    attached component objects, in their own declared order — the exact same
    PPtr(...).deref() mechanism gui_widgets.ObjectStructureTree's PPtr
    expansion already uses, no separate resolution path. A component whose
    PPtr doesn't resolve is silently skipped rather than shown as an error
    row — a dangling component reference is unusual enough, and this list
    feeds a UI (the Scene Viewer's right pane) that has no natural place to
    show a per-item error the way the structure tree's own PPtr rows do."""
    components: List[object] = []
    if game_object_obj is None:
        return components
    try:
        d = game_object_obj.parse_as_dict()
    except Exception:
        return components
    for pair in d.get("m_Component") or []:
        ptr = pair.get("component") if isinstance(pair, dict) else None
        if not isinstance(ptr, dict):
            continue
        path_id = ptr.get("m_PathID", 0)
        if not path_id:
            continue
        try:
            comp = PPtr(
                m_FileID=ptr.get("m_FileID", 0), m_PathID=path_id, assetsfile=game_object_obj.assets_file,
            ).deref()
            components.append(comp)
        except Exception:
            continue
    return components
