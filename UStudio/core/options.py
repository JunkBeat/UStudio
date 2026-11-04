"""Plain option objects EnvironmentLoader/CabArchive take as parameters, instead of
reading values live off the app's global config.CONFIG singleton — CONFIG is a
GUI-session concept (persisted via QSettings, edited through menus while a load may
be in progress); core/ needs a PyQt-free equivalent so the same loading/archive logic
is callable from a future console front end, which won't have a CONFIG object at all.
The GUI layer builds these from CONFIG today; a CLI arg parser would build them from
sys.argv later."""

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class LoadMode(Enum):
    FOLDER = "folder"
    FILES = "files"


@dataclass
class LoadOptions:
    load_mode: LoadMode
    selected_dir: str = ""
    selected_files: List[str] = field(default_factory=list)
    game_data_dir: str = ""
    managed_dir: str = ""
    game_root_dir: str = ""
    is_il2cpp: bool = False
    # IL2CPP script metadata for the TypeTreeGenerator when it is not the Windows
    # GameAssembly.dll layout (Android libil2cpp.so + global-metadata.dat, ...) — filled from
    # a platform adapter's PreparedSource, see core/platform_sources.py.
    il2cpp_binary: str = ""
    il2cpp_metadata: str = ""
    fallback_version: str = ""
    unity_cn_key: str = ""
    object_count_threshold: int = 2_000_000
    excluded_folders: List[str] = field(default_factory=list)
    # "keep_first" (default; also what any other value means) or "raise" (stop the load at
    # the first same-named-file collision) — see EnvironmentLoader.prepare_environment.
    cab_collision_policy: str = "keep_first"
    # Off by default: build_row_item() only turns an object into a table row when
    # its type is in RICH_PREVIEW_TYPES (Transform/RectTransform/MonoScript/etc.
    # never get a row) — bounds table growth on huge fixtures to the types actually
    # worth individually browsing. Checking "Загружать все ассеты" in Settings lifts
    # that filter entirely, indexing every object regardless of type. See
    # core.loader.build_row_item's own docstring for why this is safe to do (name/
    # size resolution stays cheap for any type; the filters dialog and per-type
    # preview/export dispatch already have generic fallbacks for a type outside the
    # curated set, since those already had to handle it for CAB-browser-sourced rows).
    load_all_assets: bool = False
    # User-configurable counterpart to RICH_PREVIEW_TYPES — which object type NAMES
    # build_row_item() allows through when load_all_assets is off. Empty means "use
    # RICH_PREVIEW_TYPES" (EnvironmentLoader.parse_objects() applies that fallback,
    # not this dataclass — keeps this a plain data snapshot with no import on
    # core/object_preview.py).
    indexed_types: List[str] = field(default_factory=list)
