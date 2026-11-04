"""Object reference resolution — PathID is only unique WITHIN one source file
(RowItem["source"] = obj.assets_file.name, see core/loader.py's build_row_item),
not across an entire loaded environment. Two different files can, and in
practice do, both have an object at path_id -991823019481 — silently picking
"the first match" would resolve to the wrong object without any indication
anything went wrong. Every place that takes a bare path_id from the user goes
through resolve_ref() below, which refuses to guess.

Mirrors the same (source, path_id) identity convention main.py._jump_to_object()
already uses for exactly this reason (an object's own path_id is not globally
unique, and Python object identity isn't stable across a reload either)."""

from typing import List, Optional, Tuple

from core.models import RowItem


class ObjectRefError(Exception):
    """Raised for a path_id the user gave that doesn't resolve to exactly one
    object — either none matched, or more than one did and no --source was
    given to disambiguate."""


def parse_ref(raw: str) -> Tuple[Optional[str], int]:
    """Parses "source:path_id" or a bare "path_id" (int, possibly negative —
    Unity path_ids are signed 64-bit). Returns (source_or_None, path_id)."""
    text = raw.strip()
    # rpartition, not split(":", 1) from the left: a source name could in
    # principle contain a colon (unlikely on Windows paths, but source is an
    # internal bundle entry name in the bundle-internal case, not necessarily
    # a filesystem path) — the path_id is always the LAST colon-separated part.
    source, sep, pid_text = text.rpartition(":")
    try:
        path_id = int(pid_text)
    except ValueError:
        raise ObjectRefError(
            f"not a valid object reference: {raw!r} (expected PATH_ID or SOURCE:PATH_ID)"
        )
    return (source if sep else None), path_id


def _physical_path(row: RowItem, env) -> str:
    """The path the row's file physically came from, "/"-separated ("" if unknown)."""
    try:
        return (env.source_path_of(row["obj_ref"].assets_file) or "").replace("\\", "/")
    except Exception:
        return ""


def row_matches_source(row: RowItem, source: str, env=None) -> bool:
    """A SOURCE is the file's name ("level0"), or — to tell same-named files of several
    loaded games apart — a path SUFFIX naming the folder too ("GameB/Data/level0")."""
    if row["source"] == source:
        return True
    if env is not None and ("/" in source or "\\" in source):
        wanted = source.replace("\\", "/").strip("/").lower()
        path = _physical_path(row, env).lower()
        return path == wanted or path.endswith("/" + wanted)
    return False


def source_hint(row: RowItem, env=None, parts: int = 2) -> str:
    """"folder/name" for a row's file — what to write after -S / before the colon to pick it."""
    path = _physical_path(row, env) if env is not None else ""
    segs = path.split("/") if path else []
    # Bundle-internal files (level0 inside data.unity3d) are named by their entry name; only
    # a loose file, whose own name is the source, can be qualified by its folder.
    if not segs or segs[-1].lower() != row["source"].lower():
        return row["source"]
    return "/".join(segs[-(parts + 1):])


def resolve_ref(rows: List[RowItem], path_id: int, source: Optional[str] = None, env=None) -> RowItem:
    """Returns the single RowItem matching path_id (and source, if given).
    Raises ObjectRefError — never silently picks one of several matches. With `env`, a
    SOURCE may also be a path suffix ("GameB/Data/level0") so same-named files of several
    loaded games can be told apart."""
    matches = [r for r in rows if r["path_id"] == path_id]
    if source is not None:
        matches = [r for r in matches if row_matches_source(r, source, env)]

    if not matches:
        if source is not None:
            raise ObjectRefError(f"no object with path_id {path_id} in source {source!r}")
        raise ObjectRefError(f"no object with path_id {path_id}")

    if len(matches) > 1:
        hints = sorted({source_hint(r, env) for r in matches})
        raise ObjectRefError(
            f"path_id {path_id} is ambiguous - it exists in {len(matches)} files: {', '.join(hints)}. "
            f"Disambiguate with SOURCE:PATH_ID, e.g. \"{hints[0]}:{path_id}\" "
            "(a folder before the file name tells same-named files of different games apart)."
        )

    return matches[0]


def format_ref(row: RowItem) -> str:
    """The canonical SOURCE:PATH_ID string for a row — what a user should copy
    out of `list` output to unambiguously refer to that exact object later."""
    return f"{row['source']}:{row['path_id']}"


def prefer_canonical_registration(rows: List[RowItem], env) -> List[RowItem]:
    """Collapses rows that share the identical (source, path_id) key down to
    the one backed by whichever physical file actually WON that source's
    cab-name registration (env.get_cab(source)).

    Real, confirmed case (not theoretical): a game folder with its own
    internal backup/duplicate-content subfolder — the same pattern this
    project's CLAUDE.md already documents for Petscop's BACKUP/, found again
    here for a Truck-kun fixture's own backup/ — can register TWO distinct
    SerializedFile objects both claiming the IDENTICAL source string (e.g.
    "sharedassets0.assets"): one backed by the real, current file, one by a
    stale pre-update snapshot. env.name_collisions already records which one
    won that name for cab-lookup purposes (what any real cross-file PPtr
    reference resolves through) — but session.rows/the GUI's table still
    include both files' own objects as separate rows, since row-building
    walks every loaded SerializedFile directly rather than going through the
    winner-only cab lookup. Without this filter, a bare SOURCE:PATH_ID
    reference to such an object is genuinely unable to disambiguate even
    though it already names the exact winning source string — there's
    nothing left to add to the reference that would help.

    Falls back to leaving a group's rows untouched (still genuinely
    ambiguous, exactly resolve_ref()'s existing behavior) whenever `env`
    can't resolve a winning cab for that source at all (e.g. bundle-internal
    entries with no cab-collision machinery, or `env=None`) — this never
    makes an existing case WORSE, only resolves the specific case it was
    built to find."""
    if env is None:
        return rows
    groups: "dict[Tuple[str, int], List[RowItem]]" = {}
    order: List[Tuple[str, int]] = []
    for r in rows:
        key = (r["source"], r["path_id"])
        if key not in groups:
            order.append(key)
            groups[key] = []
        groups[key].append(r)

    result: List[RowItem] = []
    for key in order:
        group = groups[key]
        if len(group) == 1:
            result.append(group[0])
            continue
        source = key[0]
        try:
            winning_cab = env.get_cab(source)
        except Exception:
            winning_cab = None
        canonical = [r for r in group if winning_cab is not None and r["obj_ref"].assets_file is winning_cab]
        result.extend(canonical if canonical else group)
    return result
