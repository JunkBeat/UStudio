"""Who refers to what — the «Сведения» tab's «Используется в» list (no Qt).

Built once per loaded game, in the background (UsageIndexRunner in usage_index_runner.py), by reading the objects
that point at assets: MonoBehaviours, Sprites, SpriteAtlases, Materials, AnimatorControllers, renderers... Their
references (core/object_references.py's walker, resolved the same way: only among files already loaded) are
reversed into target -> [(source object, field)].

Deliberately NARROW (measured on Phonopolis, 425,630 loaded objects: reading everything took 100 s and +3 GB):
- types that refer to nothing useful, or are heavy to read, are not read: AnimationClip (66 s of those 100 s —
  sprite animations are therefore not listed yet), TextAsset, textures, meshes, audio, shaders, fonts...;
- the scene hierarchy is not read (Transform/RectTransform: m_Father/m_Children — the scene viewer shows it), nor
  owner links (a component's m_GameObject, a GameObject's m_Component — «Ссылается на» shows them from the other
  side), which together were 560 k of the references;
- m_Script stays: «Используется в» on a script (MonoScript) lists its objects.
Phonopolis' sources read in ~10-15 s."""

from __future__ import annotations

import threading
import time
from array import array
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from .object_references import _collect, _loaded_file
from .progress import Pacer

_EMPTY = np.empty(0, dtype=np.int64)

# Not read as sources: heavy to read and/or refer to nothing a user looks up ("which material uses this texture").
SKIP_SOURCE_TYPES = frozenset({
    "AnimationClip", "TextAsset", "Texture2D", "Texture2DArray", "Texture3D", "Cubemap", "CubemapArray",
    "RenderTexture", "Mesh", "AudioClip", "VideoClip", "MovieTexture", "Shader", "ComputeShader", "Font",
    "Avatar", "MonoScript", "AssetBundle", "AssetBundleManifest", "PreloadData", "ResourceManager",
    "MonoManager", "BuildSettings", "PlayerSettings", "TerrainData", "NavMeshData", "LightingDataAsset",
    "OcclusionCullingData", "LightProbes", "Transform", "RectTransform", "SpriteAtlasDatabase",
})
# An object bigger than this is not read whatever its type (a huge MonoBehaviour data table, say): the time it
# would take is better spent on everything else.
MAX_SOURCE_BYTES = 4 * 1024 * 1024
# Owner links, not references: shown by «Ссылается на» from the other side.
_OWNER_FIELD = "m_GameObject"
_OWNER_PREFIX = "m_Component["


def _is_owner_link(source_type: str, field: str) -> bool:
    """Owner links and skeleton plumbing: not listed (see the module docstring). A skinned mesh's bone list
    (m_Bones[...] -> Transforms) was 66 k of Phonopolis' entries and is the skeleton, not an asset use."""
    if field == _OWNER_FIELD or field.startswith("m_Bones["):
        return True
    return source_type == "GameObject" and field.startswith(_OWNER_PREFIX)


def _parse(obj):
    """(data, node) of a source, partial when the full read fails (an IL2CPP script without its layout still has
    m_Script readable), or (None, None)."""
    try:
        node = obj._get_typetree_node()
    except Exception:
        return None, None
    try:
        return obj.parse_as_dict(), node
    except Exception:
        try:
            return obj.parse_as_dict(check_read=False), node
        except Exception:
            return None, None


class UsageIndex:
    """Build it with build() (in a background thread), then ask users(obj). `files`: the loaded SerializedFiles.

    Stored as plain numbers, not Python objects: each entry is (target file, target PathID, source file, source
    PathID, field), files and field names as small indexes into lists, in numpy arrays sorted by target; users()
    turns one target's entries back into objects when asked. Measured on Lego Party (2.76 M entries): a list of
    (object, field) tuples per target cost +716 MB, and most of it stayed with the process after a reload (the
    allocator keeps memory it handed out in many small pieces); the arrays take ~28 bytes an entry."""

    CHUNK = 400     # sources read between progress reports
    # Pacing (rest + pause while the user is busy): core.progress.Pacer. Measured here first: without it the GUI
    # froze 2-4 times for 0.2-0.46 s right after every Phonopolis load; with 10/1 ms no stall over 100 ms.

    def __init__(self, files: list, should_pause: Optional[Callable[[], bool]] = None):
        self._files = list(files)
        self._should_pause = should_pause or (lambda: False)
        self._stop = threading.Event()
        self.finished = False
        self.sources_total = 0
        self.sources_done = 0
        self._release_tables()

    def _release_tables(self) -> None:
        self._file_list: list = []                  # file number -> SerializedFile (sources and targets)
        self._file_index: Dict[int, int] = {}       # id(file) -> file number
        self._fields: List[str] = []                # field number -> field path
        self._file_bounds: List[int] = [0]          # file number n's entries: [bounds[n], bounds[n + 1])
        self._target_file = self._target_pid = self._source_file = self._source_pid = self._field = _EMPTY

    def _file_no(self, sf) -> int:
        key = id(sf)
        no = self._file_index.get(key)
        if no is None:
            no = self._file_index[key] = len(self._file_list)
            self._file_list.append(sf)
        return no

    def stop(self) -> None:
        self._stop.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    @property
    def entry_count(self) -> int:
        return len(self._target_pid)

    def _sources(self):
        for sf in self._files:
            for obj in list(sf.objects.values()):
                try:
                    if obj.type.name in SKIP_SOURCE_TYPES or (getattr(obj, "byte_size", 0) or 0) > MAX_SOURCE_BYTES:
                        continue
                except Exception:
                    continue
                yield obj

    def build(self, on_progress: Optional[Callable[[int, int], None]] = None) -> bool:
        """Reads every source; True when finished, False when stopped. Pauses while should_pause() says the user is
        busy, and lets the GUI thread run between chunks."""
        sources = list(self._sources())
        self.sources_total = len(sources)
        files: dict = {}
        field_no: Dict[str, int] = {}
        fields = self._fields
        target_file, target_pid = array("i"), array("q")
        source_file, source_pid, field_col = array("i"), array("q"), array("i")
        file_no = self._file_no
        stop = self._stop
        pacer = Pacer(self._should_pause, stop.is_set)
        for i, obj in enumerate(sources):
            if not pacer.step():
                return False
            if i % self.CHUNK == 0:
                if stop.is_set():
                    return False
                while self._should_pause() and not stop.is_set():
                    time.sleep(Pacer.BUSY_SLEEP_S)      # the first chunk too (pacer.step() waits only at a slice end)
                self.sources_done = i
                if on_progress is not None:
                    on_progress(i, self.sources_total)
            data, node = _parse(obj)
            if data is None or node is None:
                continue
            found: list = []
            for child in node.m_Children:
                _collect(child, data.get(child.m_Name) if isinstance(data, dict) else None, child.m_Name, found)
            if not found:
                continue
            source_type = obj.type.name
            assets_file = obj.assets_file
            src_no = None
            for field, _declared, file_id, path_id in found:
                if _is_owner_link(source_type, field):
                    continue
                key = (id(assets_file), file_id)
                if key in files:
                    target = files[key]
                else:
                    target = _loaded_file(assets_file, file_id)
                    target = files[key] = None if target is None else file_no(target)
                if target is None:
                    continue
                if src_no is None:
                    src_no = file_no(assets_file)
                no = field_no.get(field)
                if no is None:
                    no = field_no[field] = len(fields)
                    fields.append(field)
                target_file.append(target)
                target_pid.append(path_id)
                source_file.append(src_no)
                source_pid.append(obj.path_id)
                field_col.append(no)
        del sources, files
        tf = np.frombuffer(target_file, dtype=np.int32)
        tp = np.frombuffer(target_pid, dtype=np.int64)
        order = np.lexsort((tp, tf))            # by target file, then PathID; stable: sources keep reading order
        self._target_file, self._target_pid = tf[order], tp[order]
        self._source_file = np.frombuffer(source_file, dtype=np.int32)[order]
        self._source_pid = np.frombuffer(source_pid, dtype=np.int64)[order]
        self._field = np.frombuffer(field_col, dtype=np.int32)[order]
        # once, as plain ints: a search of the int32 column with a Python int converted the whole column per call
        self._file_bounds = np.searchsorted(
            self._target_file, np.arange(len(self._file_list) + 1, dtype=np.int32)).tolist()
        self.sources_done = self.sources_total
        self.finished = True
        if on_progress is not None:
            on_progress(self.sources_total, self.sources_total)
        return True

    def users(self, obj) -> Optional[List[Tuple[object, str]]]:
        """[(source object, field)] referring to `obj` — None while the index is not finished."""
        if not self.finished:
            return None
        no = self._file_index.get(id(obj.assets_file))
        if no is None:
            return []
        lo, hi = self._file_bounds[no], self._file_bounds[no + 1]
        pids = self._target_pid[lo:hi]
        start = lo + int(np.searchsorted(pids, obj.path_id, "left"))
        end = lo + int(np.searchsorted(pids, obj.path_id, "right"))
        out = []
        file_list, fields = self._file_list, self._fields
        for sf_no, pid, fno in zip(self._source_file[start:end].tolist(), self._source_pid[start:end].tolist(),
                                   self._field[start:end].tolist()):
            source = file_list[sf_no].objects.get(pid)
            if source is not None:
                out.append((source, fields[fno]))
        return out

    def release(self) -> None:
        """Drop every object reference (the game is being closed or reloaded)."""
        self.stop()
        self._release_tables()
        self._files = []
