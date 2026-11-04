import os
import threading
from typing import Dict, List, Tuple, Optional

from .TypeTreeNode import TypeTreeNode

# Same bit TypeTreeHelper.metaflag_is_aligned() checks — kept as a local literal
# rather than importing TypeTreeHelper.kAlignBytes to avoid a circular import
# (TypeTreeHelper doesn't import this module, but ObjectReader imports both, and
# this module is lower-level / more widely depended on).
_kAlignBytes = 0x4000

# TypeTreeGeneratorAPI (the third-party native/.NET generator this module wraps —
# no vendored source to patch directly) hardcodes a standard MonoBehaviour header
# ahead of a script's own reflected fields, and that hardcoded template's "m_Enabled"
# node is missing the align-after-read bit: confirmed by direct comparison against
# UnityPy's own TPK-based generic MonoBehaviour header (UnityPy.helpers.Tpk),
# which correctly marks m_Enabled aligned (0x4101, bit 0x4000 set) for the same
# Unity version, while every OTHER standard header field (m_GameObject, m_Script,
# m_Name) and every genuinely user-script-reflected field (confirmed via a real
# fixture's own custom bool field, which DOES carry the bit) come through fine —
# this is specific to the generator's own hardcoded m_Enabled node, not a general
# alignment problem. Missing this bit means read_value()/read_typetree_boost never
# skip the 3 padding bytes Unity's actual file format still physically has after a
# lone 1-byte field, desyncing every field read after it for the rest of the
# object — confirmed via a real-world report: a PPtr right after m_Enabled (e.g.
# MonoBehaviour's own m_Script) coming back with m_FileID/m_PathID inflated by
# exactly 2**24 (a textbook signature of a 3-byte-early stream read), and
# reproduced directly against a real fixture (Truck-kun, Unity 6000.0.51f1):
# 91,396/91,618 MonoBehaviours affected once TypeTreeGeneratorAPI's real DLL-backed
# generator was wired up, 0/91,619 when parsed via the TPK-based generic header
# instead (no generator) — isolating the bug to this one hardcoded node.
_KNOWN_MISSING_ALIGN_FIELDS = frozenset({"m_Enabled"})

try:
    from TypeTreeGeneratorAPI import TypeTreeGenerator as TypeTreeGeneratorBase  # pyright: ignore[reportAssignmentType]
except ImportError:

    class TypeTreeGeneratorBase:
        def __init__(self, unity_version: str):
            raise ImportError("TypeTreeGeneratorAPI isn't installed!")

        def load_dll(self, dll: bytes): ...
        def load_il2cpp(self, il2cpp: bytes, metadata: bytes): ...
        def get_nodes_as_json(self, assembly: str, fullname: str) -> str: ...
        def get_nodes(self, assembly: str, fullname: str) -> List[TypeTreeNode]: ...


# Type names whose node legitimately owns a lone `Array` child, i.e. that are NOT a plain
# List<T>/T[] and must keep their name (see _corrected_types()).
_ARRAY_OWNING_TYPES = frozenset({"vector", "map", "set", "staticvector", "TypelessData", "string"})


def _corrected_types(base_nodes) -> List[str]:
    """Node type names for the generator's flat node list, with the native generator's
    mislabelled list containers put right.

    Real bug in the third-party TypeTreeGeneratorAPI (0.0.10 — the latest release; no
    vendored source to patch): for a `List<string>` / `string[]` field it names the
    CONTAINER node `string` instead of `vector` (and for a list of a custom class it
    names it after the element class, e.g. `TextTableField m_fieldValues`), while
    `List<int>` and friends come out right. Confirmed against a real fixture
    (Kindergarten 3, `TextTable`, Unity 2022.3.5): the container's own children are
    the correct `Array { int size; string data }`, only its type name is wrong.

    It is not cosmetic. TypeTreeHelper.read_value()/write_value() (and the C++
    accelerator) consult the type name BEFORE the node's shape, and `string` means
    "int length + that many chars": the list's element count was read as a string
    length and every field after it desynced — surfacing as `read_int_array out of
    bounds` / `read_str out of bounds` on any script with such a field (also breaking
    writes of edited data). A class-named container happens to survive because the
    reader falls through to its structural "first child is Array" test, but it is
    mislabelled all the same (dump/structure views show the element class as the type).

    A genuine string is unmistakable — its Array's element is `char` — so that is the
    discriminator; any other node whose ONLY child is a size+data `Array` and whose type
    isn't one of the legitimate array-owning types is a list and becomes `vector`, which
    is what Unity itself writes for List<T>/T[]."""
    n = len(base_nodes)
    types = [b.m_Type for b in base_nodes]
    for i, node in enumerate(base_nodes):
        j = i + 1
        if j + 2 >= n:
            continue
        array, size, data = base_nodes[j], base_nodes[j + 1], base_nodes[j + 2]
        level = node.m_Level
        if not (array.m_Level == level + 1 and array.m_Type == "Array" and array.m_Name == "Array"
                and size.m_Level == level + 2 and data.m_Level == level + 2 and size.m_Name == "size"):
            continue
        # The Array must be the node's ONLY child: the first node after its subtree is not a sibling.
        k = j + 1
        while k < n and base_nodes[k].m_Level > array.m_Level:
            k += 1
        if k < n and base_nodes[k].m_Level > level:
            continue
        if node.m_Type == "string":
            if data.m_Type != "char":
                types[i] = "vector"
        elif node.m_Type not in _ARRAY_OWNING_TYPES:
            types[i] = "vector"
    return types


class TypeTreeGenerator(TypeTreeGeneratorBase):
    cache: Dict[Tuple[str, str], Optional[TypeTreeNode]]

    def __init__(self, unity_version: str, *args, **kwargs):
        super().__init__(unity_version, *args, **kwargs)
        self.cache = {}
        # Guards both the cache dict AND the native call below — see get_nodes_up()'s
        # own docstring for the real, reproduced concurrent-caller corruption this
        # closes. One shared TypeTreeGenerator instance (env.typetree_generator) is
        # used for the whole app session, and this app genuinely calls into it from
        # more than one thread (the GUI thread's own MonoBehaviour/script-name
        # resolution, and any background task-queue job that touches a MonoBehaviour-
        # classed object — e.g. TMP_FontAsset's SDF generation) with no coordination
        # otherwise — the underlying native generator (self.ptr, TypeTreeGeneratorAPI.dll)
        # was never verified reentrant and has no documented thread-safety guarantee.
        self._lock = threading.Lock()

    def load_local_game(self, root_dir: str):
        root_files = os.listdir(root_dir)
        data_dir = os.path.join(root_dir, next(f for f in root_files if f.endswith("_Data")))
        if "GameAssembly.dll" in root_files:
            ga_fp = os.path.join(root_dir, "GameAssembly.dll")
            gm_fp = os.path.join(data_dir, "il2cpp_data", "Metadata", "global-metadata.dat")
            with open(ga_fp, "rb") as f:
                ga_raw = f.read()
            with open(gm_fp, "rb") as f:
                gm_raw = f.read()
            self.load_il2cpp(ga_raw, gm_raw)
        else:
            self.load_local_dll_folder(os.path.join(data_dir, "Managed"))

    def load_local_dll_folder(self, dll_dir: str):
        for f in os.listdir(dll_dir):
            if not f.endswith(".dll"):
                continue
            fp = os.path.join(dll_dir, f)
            with open(fp, "rb") as f:
                data = f.read()
                self.load_dll(data)

    def get_nodes_up(self, assembly: str, fullname: str) -> TypeTreeNode:
        """Real, reproduced bug this lock closes (not theoretical): this app calls
        get_nodes_up() concurrently from the GUI thread (bulk MonoBehaviour
        script-name resolution — e.g. activating a script-restricted Quick Filter
        forces every unresolved MonoBehaviour row to resolve at once) and from a
        background worker thread (any task-queue job touching a MonoBehaviour-
        classed object, e.g. SDF font-atlas generation on a TMP_FontAsset). Without
        a lock, two threads can both miss the cache for the same (or a different)
        key and both call the native self.get_nodes(...) — a plain ctypes call,
        which releases the GIL for its duration — on the SAME underlying native
        generator instance (self.ptr) at once. Reproduced directly: hammering this
        exact call concurrently against a real fixture produced corrupted reads
        (EOFError: read_str out of bounds), garbage dict lookups (KeyError on a
        PathID-shaped value that doesn't exist), and "Negative length read from
        TypeTree" — the same corruption family that, given unlucky timing at real
        game object counts, escalates into an actual out-of-bounds memory access
        (a Windows access violation)."""
        with self._lock:
            key = (assembly, fullname)
            if key in self.cache:
                cached = self.cache[key]
                if cached is None:
                    raise ValueError(f"Previously failed to resolve node for {fullname} ({assembly})")
                return cached

            if not assembly.endswith(".dll"):
                assembly = f"{assembly}.dll"

            try:
                base_nodes = self.get_nodes(assembly, fullname)
            except Exception as e:
                self.cache[key] = None   # remember the failure so we don't hit the native call again
                raise ValueError(f"Native generator failed for {fullname} ({assembly}): {e}") from e

            corrected_types = _corrected_types(base_nodes)
            node = TypeTreeNode.from_list(
                [
                    TypeTreeNode(
                        base_node.m_Level, corrected_types[index], base_node.m_Name, 0, 0,
                        m_MetaFlag=(
                            (base_node.m_MetaFlag or 0) | _kAlignBytes
                            if base_node.m_Name in _KNOWN_MISSING_ALIGN_FIELDS
                            else base_node.m_MetaFlag
                        ),
                    )
                    for index, base_node in enumerate(base_nodes)
                ]
            )
            self.cache[key] = node
            return node


__all__ = ("TypeTreeGenerator",)
