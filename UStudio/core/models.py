"""Plain data shapes shared between core/ and the GUI layer — no PyQt dependency."""

from typing import TypedDict

from UnityPy.files.ObjectReader import ObjectReader


class _RowItemRequired(TypedDict):
    type: str
    name: str
    # Asset-bundle "container" path (e.g. "assets/textures/foo.png") — Unity's own
    # addressables/AssetBundle.m_Container mapping, distinct from `source` (which
    # bundle/file the object came from). Empty string when the object has no
    # container entry (most objects don't — only ones explicitly added to a bundle
    # via BuildPipeline do), never None, so the table can always display/sort it.
    container_path: str
    # MonoBehaviour's referenced script class name (e.g. "PlayerController") — a
    # separate concern from `name` (the object's own m_Name, same field every
    # other type has). Empty string for every non-MonoBehaviour row.
    script_name: str
    source: str
    path_id: int
    size: int
    obj_ref: ObjectReader


class RowItem(_RowItemRequired, total=False):
    """One row of the main object table. raw_bytes is populated lazily (only once
    something has already read it via get_raw_data()), hence total=False."""
    raw_bytes: bytes
