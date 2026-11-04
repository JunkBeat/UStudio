from __future__ import annotations

from typing import TYPE_CHECKING, Any, Generic, Optional, TypeVar, cast

from attr import define

if TYPE_CHECKING:
    from ..enums.ClassIDType import ClassIDType
    from ..files.ObjectReader import ObjectReader
    from ..files.SerializedFile import SerializedFile

T = TypeVar("T")


@define(slots=True, kw_only=True)
class PPtr(Generic[T]):
    m_FileID: int
    m_PathID: int
    assetsfile: Optional[SerializedFile] = None

    @property
    def file_id(self) -> int:
        # backwards compatibility
        return self.m_FileID

    @property
    def path_id(self) -> int:
        # backwards compatibility
        return self.m_PathID

    @property
    def type(self) -> ClassIDType:
        return self.deref().type

    # backwards compatibility - to be removed in UnityPy 2
    def read(self):
        return self.deref_parse_as_object()

    # backwards compatibility - to be removed in UnityPy 2
    def read_typetree(self):
        return self.deref_parse_as_dict()

    def deref(self, assetsfile: Optional[SerializedFile] = None, include_skipped: bool = False) -> ObjectReader[T]:
        # include_skipped: also find an object a type-filtered load skipped (SerializedFile.skipped_object) — a
        # reader that is not in the file's objects while only read (its first edit adopts it into them, so the
        # edit is saved: SerializedFile.adopt_skipped). Off by default: every
        # existing caller keeps the old behaviour (KeyError for a skipped object).
        assetsfile = assetsfile or self.assetsfile

        if assetsfile is None:
            raise ValueError("PPtr can't deref without an assetsfile!")

        if self.m_PathID == 0:
            raise ValueError("PPtr can't deref with m_PathID == 0!")

        assetsfile_dst = None
        if self.m_FileID == 0:
            assetsfile_dst = assetsfile or self.assetsfile
        else:
            # resolve file id to external name
            external_id = self.m_FileID - 1
            if external_id >= len(assetsfile.externals):
                raise FileNotFoundError("Failed to resolve pointer - invalid m_FileID!")
            external = assetsfile.externals[external_id]

            # resolve external name to assetsfile
            container = assetsfile.parent
            if container is None:
                # TODO - use default fs
                raise FileNotFoundError(f"PPtr points to {external.path} but no container is set!")

            external_clean_path = external.path
            if external_clean_path.startswith("archive:/"):
                external_clean_path = external_clean_path[9:]
            if external_clean_path.startswith("assets/"):
                external_clean_path = external_clean_path[7:]
            external_clean_path = external_clean_path.rsplit("/")[-1].lower()

            # container is the top-level Environment exactly when assetsfile is a
            # direct (non-bundle-internal) load — File.environment always resolves
            # up to the same root Environment regardless of nesting depth, but
            # .parent is only ever equal to it for a file with no bundle between it
            # and the root. That case's container.files is Environment.files,
            # keyed by full source PATHS — a bare lowercased basename can
            # structurally never equal one, so this scan is guaranteed-wasted work
            # there: confirmed via profiling a real ~530k-object folder load, where
            # this exact loop (unconditional before this fix) accounted for 114s of
            # 146s total (~78%) — 179M wasted .lower() calls across ~100k PPtr
            # derefs, an O(files_loaded) scan per deref that NEVER matched even
            # once, always falling through to find_file()'s cheap O(1) lookup
            # below regardless. Skipped entirely in that case now. Bundle-internal
            # files (container is the BundleFile, not the Environment) keep the
            # scan: BundleFile.files is keyed by the actual short internal entry
            # names, which CAN legitimately match after lowering, and a bundle's
            # entry count is small enough that an O(n) scan there is cheap anyway.
            if container is not assetsfile.environment:
                for key, file in container.files.items():
                    if key.lower() == external_clean_path:
                        assetsfile_dst = file
                        break

            if assetsfile_dst is None:
                env = assetsfile.environment
                # With several same-named files loaded (two games, or a game and its
                # backup copy), the reference belongs to the one nearest the file that
                # holds this pointer, not to whichever took the name slot first.
                picked = env.pick_cab_alternative(external_clean_path, assetsfile) if hasattr(env, "pick_cab_alternative") else None
                if picked is not None and hasattr(picked[1], "objects"):
                    assetsfile_dst = picked[1]
            if assetsfile_dst is None:
                env = assetsfile.environment
                cab = env.find_file(external_clean_path)
                if cab:
                    assetsfile_dst = cab
                else:
                    raise FileNotFoundError(f"Failed to resolve pointer - {external.path} not found!")

        if assetsfile_dst is None:
            raise FileNotFoundError(f"Failed to resolve pointer - {self.m_FileID} not found!")

        if include_skipped and self.m_PathID not in assetsfile_dst.objects:
            skipped = assetsfile_dst.skipped_object(self.m_PathID)
            if skipped is not None:
                return cast("ObjectReader[T]", skipped)
        return cast("ObjectReader[T]", assetsfile_dst.objects[self.m_PathID])

    def deref_parse_as_object(self, assetsfile: Optional[SerializedFile] = None, include_skipped: bool = False) -> T:
        return self.deref(assetsfile, include_skipped).parse_as_object()

    def deref_parse_as_dict(self, assetsfile: Optional[SerializedFile] = None) -> dict[str, Any]:
        return self.deref(assetsfile).parse_as_dict()

    def __bool__(self):
        return self.m_PathID != 0

    def __hash__(self) -> int:
        return hash((self.m_FileID, self.m_PathID))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PPtr):
            return False
        return self.m_FileID == other.m_FileID and self.m_PathID == other.m_PathID


__all__ = [
    "PPtr",
]
