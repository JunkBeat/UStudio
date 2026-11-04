"""PyQt-free detection of "this looks like more than one Unity game was loaded
together" — shared by the GUI (cab_collision_handler.py, via a QMessageBox)
and the CLI (cli/commands.py, via a plain stderr line), so the two surfaces
can't drift on what counts as a collision worth interrupting for.

A cab-name collision (env.name_collisions) fires for ANY two same-named
files, including harmless ones (two folders shipping the identical Mono
runtime DLL/config, say) that have zero effect on what ends up in the table.
Only a collision where BOTH sides are a real, object-bearing SerializedFile
(not a bare EndianBinaryReader for a plain file, and not a SerializedFile
that happened to parse to zero objects) is the kind that actually produces
wrong-texture-reads/duplicate-looking rows — see the "Emily is Away Too"
fixture (two independent games each shipping their own resources.assets)
that surfaced this."""

from typing import List


def _has_objects(item) -> bool:
    # Imported lazily so importing this module doesn't require UnityPy's
    # SerializedFile to already be resolvable at collision_report import
    # time — same reasoning core/sdf_map.py gives for its own local
    # core.sdf_resolver import.
    from UnityPy.files import SerializedFile
    return isinstance(item, SerializedFile) and bool(item.objects)


def meaningful_collisions(collisions) -> List:
    """Filters env.name_collisions down to only the pairs where both sides
    actually hold Unity objects — the ones worth warning about."""
    if not collisions:
        return []
    return [c for c in collisions if _has_objects(c.kept_item) and _has_objects(c.rejected_item)]
