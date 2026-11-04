"""Recognising a MonoBehaviour's script from the fields of its type tree.

A MonoBehaviour names its script only through the m_Script reference, and the MonoScript it points to can
live in a file that was not loaded (a missing Addressables scripts bundle, say). The object's own type tree
still lists its fields, and some well-known classes are unmistakable by them. This module holds that
knowledge: which classes are known, and which fields (with which types) identify each one.

Pure data and matching - no UnityPy, no Qt, and no import of core.file_utils (which calls recognise() from
peek_mb_identity()), so there is no import cycle. Reading the fields off an object, caching and telling the
user is core.file_utils' job.

Adding a class: one entry in _SIGNATURES, with a layout taken from REAL files (every field of a layout must be
present with one of the listed types, so names that another class merely reuses do not match). Do not add one
from memory - the first draft of the TMP_FontAsset entry missed a whole generation of fonts that way.

Type names: a type tree embedded in a file names a list by its element type ("Glyph"), one generated from the
game's assemblies calls it "vector"; both are listed where a field is a list.
"""

from typing import Dict, FrozenSet, NamedTuple, Optional, Tuple


class KnownScript(NamedTuple):
    class_name: str
    namespace: str
    assembly_name: str


# {field name: the type names that field has on real files}
Layout = Dict[str, FrozenSet[str]]

TMP_FONT_ASSET = KnownScript("TMP_FontAsset", "TMPro", "Unity.TextMeshPro")

# TextMeshPro font assets, two generations, taken from real files (26 fonts of 4 games, the Two Point font
# bundles, Emily is Away Too, Petscop):
#   * TMP 1.4+: m_GlyphTable / m_CharacterTable;
#   * the older package (pre-1.4.0; Emily is Away Too, Petscop): m_fontInfo / m_glyphInfoList /
#     fontAssetType / m_kerningInfo. (Emily's fonts also have fontCreationSettings, Petscop's do not -
#     it is not part of the layout.)
_TMP_FONT_ASSET_LAYOUTS: Tuple[Layout, ...] = (
    {
        "m_FaceInfo": frozenset({"FaceInfo"}),
        "m_GlyphTable": frozenset({"vector", "Glyph"}),
        "m_CharacterTable": frozenset({"vector", "TMP_Character"}),
        "m_AtlasTextures": frozenset({"vector"}),
        "m_AtlasWidth": frozenset({"int"}),
    },
    {
        "m_fontInfo": frozenset({"FaceInfo"}),
        "m_glyphInfoList": frozenset({"vector", "TMP_Glyph"}),
        "fontAssetType": frozenset({"int"}),
        "m_kerningInfo": frozenset({"KerningTable"}),
    },
)

_SIGNATURES: Tuple[Tuple[KnownScript, Tuple[Layout, ...]], ...] = (
    (TMP_FONT_ASSET, _TMP_FONT_ASSET_LAYOUTS),
)


def _has_layout(field_types: Dict[str, str], layout: Layout) -> bool:
    return all(field_types.get(name) in accepted for name, accepted in layout.items())


def recognise(field_types: Dict[str, str]) -> Optional[KnownScript]:
    """The known script whose layout `field_types` ({field name: type name} of a MonoBehaviour's type tree)
    contains in full, or None."""
    for script, layouts in _SIGNATURES:
        if any(_has_layout(field_types, layout) for layout in layouts):
            return script
    return None
