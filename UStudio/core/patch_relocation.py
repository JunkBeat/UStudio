"""Moving a folder of patch files onto a newer build of the game: proposals and renamed copies.

A patch is named after the object it was exported from: "Name #PathID (source).ext" (build_export_stem). A game
update renumbers objects (measured on a real Phonopolis update: 71 % of the textures and 94 % of the MonoBehaviours
moved), so most patches no longer name their object. This module PROPOSES where each one went; it never decides
alone - the GUI (tools/patch_relocation_tool.py) shows every proposal and the user accepts it. Nothing here touches
the patch folder or the game; write_copies() writes renamed copies into a NEW folder, for the usual folder import.

Steps:
  1. scan_entries()       the importable patches of a folder, by NAME only (no file is opened)
  2. propose()            against the rows of the updated game, the same rules as the measured POC
                          (dev_scripts/patch_match_report.py, 96-100 % right where it gives an answer):
                          the same name in the same file; several -> the one moved by the PathID shift of the
                          nearest certain neighbours; nameless -> the old PathID + a neighbour's shift; the same
                          name in another file; never two patches of one kind on one object
  3. settle_by_content()  a patch several objects fit is placed by its own content when exactly one matches it
                          clearly best
  4. write_copies()       the accepted ones under their new names; a .dump.json gets the new object's references
                          (m_Script, m_GameObject, ...) - otherwise the import's content check refuses it - and
                          the fields the update added or removed

The old build's objects (to measure the proposals against the truth) are in dev_scripts/patch_relocation_old.py.

No Qt. Sources ending with IGNORED_SUFFIXES (".ORIGINAL": copies a mod installer leaves next to the game's files)
are left out on both sides.
"""

from core.i18n import N_, tr
import bisect
import json
import logging
import os
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .object_common import resolve_script_name
from .object_export import build_export_stem, sanitize_export_filename
from .patch_matching import scan_patch_folder, types_for_converted_suffix

logger = logging.getLogger(__name__)

IGNORED_SUFFIXES = (".ORIGINAL",)

# Statuses.
ON_SPOT = "on_spot"        # the slot still holds an object of that name: nothing to rename
BY_NAME = "by_name"        # a proposal from name + neighbours (or the patch's own content)
AMBIGUOUS = "ambiguous"    # several candidates: the user picks one
NAMELESS = "nameless"      # a nameless patch nothing places
LOST = "lost"              # no object of that name

# How the place was found, or why it was not (PatchEntry.how). Codes, not text: the window and the report word them.
HOW_SPOT = "spot"                            # the slot still holds an object of that name
HOW_SCRIPT_UNREAD = "script_unread"          # the slot's script cannot be resolved: only the place was checked
HOW_SAME_FILE = "same_file"                  # the only object of that name in the patch's file
HOW_NEIGHBOURS = "neighbours"                # one of `count` same-named objects, moved like the neighbouring patches
HOW_OTHER_FILE = "other_file"                # the only object of that name, in another file
HOW_NAMELESS_NEIGHBOURS = "nameless_neighbours"  # nameless: old PathID + the neighbouring patches' shift
HOW_CONTENT = "content"                      # one of `count` candidates; only its content matches the patch
HOW_SEVERAL = "several"                      # `count` same-named objects, nothing tells them apart
HOW_IDENTICAL = "identical"                  # `count` candidates have exactly the patch's content
HOW_CLAIMED = "claimed"                      # `count` patches of one kind point at the same object
HOW_NAMELESS_UNPLACED = "nameless_unplaced"  # nameless, no neighbouring patch gives the place
HOW_SAME_SCRIPT = "same_script"              # no object of that name; candidates = objects of its script
HOW_NO_NAME = "no_name"                      # no object of that name at all
HOW_CANT_TELL = "cant_tell"                  # a dump `count` objects fit and nothing a person can see tells them apart

# How many candidates a nameless / lost patch offers to pick from (nearest to where it should be).
MAX_PICK_CANDIDATES = 20

REPORT_NAME = "report.txt"

CancelCheck = Optional[Callable[[], bool]]
Progress = Optional[Callable[[str, int, int], None]]


@dataclass
class PatchEntry:
    path: Path
    rel: Path                # relative to the patch folder (subfolders are kept in the copy)
    path_id: int             # the patch's (old) PathID
    source: str              # the patch's source, as in its name
    mode: str                # json_dump | raw | content_raw | converted
    declared: str            # the name part of its file name ("Script.Object" for a MonoBehaviour)
    tail: str                # what follows "(source)" in the file name: ".dump.json", ".png", ...
    status: str = ""
    how: str = ""            # HOW_*: how the place was found, or why it was not (a code; the window words it)
    count: int = 0           # the number HOW_* speaks of (same-named objects, identical ones, patches claiming one)
    target: Any = None       # the proposed object of the new build (None: no proposal)
    candidates: List[Any] = field(default_factory=list)   # what the user may pick from (target first, if any)
    decision: Optional[str] = None    # None (undecided) | "accept" | "skip"
    chosen: Any = None       # the object an accepted patch goes to (target, or a picked candidate)
    patch_text: str = ""     # a dump to choose for: its text a person recognises (drop_guesses)
    candidate_texts: Dict[int, str] = field(default_factory=dict)   # id(candidate) -> that object's text in the game

    @property
    def nameless(self) -> bool:
        return _is_nameless(self.declared)

    @property
    def state(self) -> str:
        """What the window says, from the patch alone: "on_spot" (its object is where it was), "found" (one object
        by name and place), "choose" (several fit: the user picks), "lost" (nothing fits)."""
        if self.status == ON_SPOT:
            return "on_spot"
        if self.status == BY_NAME and self.target is not None:
            return "found"
        if self.candidates:
            return "choose"
        return "lost"

    @property
    def checked(self) -> bool:
        """Whether the patch is written: "on_spot" / "found" ones unless the user unticks them, the others only
        once the user ticks them (a variant picked)."""
        if self.decision == "skip":
            return False
        if self.decision == "accept":
            return True
        return self.state in ("on_spot", "found")

    def final_target(self):
        """The object this patch is written for, or None when it is not written."""
        if not self.checked:
            return None
        if self.chosen is not None:
            return self.chosen
        if self.target is not None:
            return self.target
        return self.candidates[0] if self.candidates else None


def _type_names() -> set:
    from UnityPy.enums import ClassIDType
    return set(ClassIDType.__members__)


_TYPE_NAMES: Optional[set] = None


def _is_nameless(declared: str) -> bool:
    global _TYPE_NAMES
    if _TYPE_NAMES is None:
        _TYPE_NAMES = _type_names()
    return declared.endswith(".Unnamed") or declared in _TYPE_NAMES


def _ignored(source: str, ignore) -> bool:
    return str(source).endswith(tuple(ignore))


def scan_entries(folder: Path, ignore=IGNORED_SUFFIXES) -> Tuple[List[PatchEntry], int]:
    """The importable patches of `folder` (recursive, names only) and how many of ignored sources were left out."""
    folder = Path(folder)
    entries, ignored = [], 0
    for path, m, mode in scan_patch_folder(folder).importable:
        if _ignored(m.group(2), ignore):
            ignored += 1
            continue
        entries.append(PatchEntry(path, path.relative_to(folder), int(m.group(1)), m.group(2), mode,
                                  path.name[:m.start()].rstrip(), path.name[m.end():]))
    entries.sort(key=lambda e: str(e.rel).lower())
    return entries, ignored


def object_label(obj) -> str:
    """«Name #PathID (file)» - how an object is named in the window and the report."""
    try:
        return build_export_stem(obj)
    except Exception:
        return f"#{obj.path_id} ({obj.assets_file.name})"


def new_file_name(entry: PatchEntry, obj) -> str:
    return build_export_stem(obj) + entry.tail


# ---------------------------------------------------------------------------------------------- the new build


class GameIndex:
    """The updated game's rows by (source, PathID), by name and by file - built once per check."""

    def __init__(self, rows, ignore=IGNORED_SUFFIXES, should_cancel: CancelCheck = None, progress: Progress = None):
        self.slot: Dict[Tuple[str, int], Tuple[Any, str]] = {}
        self.by_name: Dict[str, List[Tuple[Any, str]]] = defaultdict(list)
        self.by_file: Dict[str, List[Tuple[int, Any, str]]] = defaultdict(list)
        self.scripts = Counter()
        total = len(rows)
        for i, r in enumerate(rows):
            if i % 2000 == 0:
                if should_cancel and should_cancel():
                    from .progress import OperationCancelled
                    raise OperationCancelled()
                if progress:
                    progress(tr("Читаются имена объектов игры…"), i, total)
            if _ignored(r["source"], ignore):
                continue
            obj = r["obj_ref"]
            source = sanitize_export_filename(str(r["source"]), fallback="unknown")
            try:
                name = build_export_stem(obj).split(f" #{obj.path_id}", 1)[0]
            except Exception:
                continue
            self.slot.setdefault((source, obj.path_id), (obj, name))
            self.by_name[name].append((obj, source))
            self.by_file[source].append((obj.path_id, obj, name))
            if obj.type.name == "MonoBehaviour":
                self.scripts[name.split(".", 1)[0]] += 1
        for lst in self.by_file.values():
            lst.sort(key=lambda t: t[0])

    def kin(self, source: str, entry: PatchEntry, obj_type: Optional[str] = None) -> List[Tuple[int, Any, str]]:
        """Objects of `source` of the patch's kind: `obj_type` when known (a MonoBehaviour: of the patch's
        script too), else what its name says - "Script.Unnamed" / "Script.Name" a MonoBehaviour of that script
        (when such a script exists), a bare type name that type."""
        script = None
        if obj_type is None:
            first = entry.declared.split(".", 1)[0]
            if "." in entry.declared and self.scripts.get(first):
                obj_type, script = "MonoBehaviour", first
            elif _is_nameless(entry.declared):
                obj_type = entry.declared
            else:
                return []
        elif obj_type == "MonoBehaviour":
            script = entry.declared.split(".", 1)[0]
        out = []
        for pid, obj, name in self.by_file.get(source, ()):
            if obj.type.name != obj_type or not _fits(obj, entry):
                continue
            if script is not None and name.split(".", 1)[0] != script:
                continue
            out.append((pid, obj, name))
        return out


def _fits(obj, entry: PatchEntry) -> bool:
    if entry.mode != "converted":
        return True                            # a dump fits any type; the name decides
    kinds = types_for_converted_suffix(entry.path.name)
    return kinds is None or obj.type.name in kinds


def propose(entries: List[PatchEntry], index: GameIndex) -> None:
    """Fills status / how / target / candidates of every entry from names and neighbours alone
    (the POC's classify(), measured right in 96-100 % of the checked answers)."""
    pending, later = [], []
    anchors = defaultdict(list)                # source -> [(old pid, PathID shift)] from NAMED patches only
    for e in entries:
        e.status, e.how, e.count, e.target, e.candidates = "", "", 0, None, []
        e.decision, e.chosen = None, None
        e.patch_text, e.candidate_texts = "", {}
        here = index.slot.get((e.source, e.path_id))
        if here is not None and here[0].type.name == "MonoBehaviour" and resolve_script_name(here[0]) == "Unknown":
            e.status, e.target, e.candidates = BY_NAME, here[0], [here[0]]
            e.how = HOW_SCRIPT_UNREAD
            continue
        if e.nameless:
            later.append(e)
            continue
        cands = [(o, s) for o, s in index.by_name.get(e.declared, ()) if _fits(o, e)]
        same_file = [o for o, s in cands if s == e.source]
        if here is not None and here[1] == e.declared:
            e.status, e.target, e.candidates, e.how = ON_SPOT, here[0], [here[0]], HOW_SPOT
            anchors[e.source].append((e.path_id, 0))
        elif len(same_file) == 1:
            e.status, e.target, e.candidates = BY_NAME, same_file[0], [same_file[0]]
            e.how = HOW_SAME_FILE
            anchors[e.source].append((e.path_id, same_file[0].path_id - e.path_id))
        else:
            pending.append((e, cands, same_file))
    for lst in anchors.values():
        lst.sort()

    def shifts(source, pid):
        lst = anchors.get(source, [])
        k = bisect.bisect_left(lst, (pid, -10 ** 30))
        return [lst[j][1] for j in (k - 1, k) if 0 <= j < len(lst)]

    for e, cands, same_file in pending:
        if len(same_file) > 1:
            near = set(shifts(e.source, e.path_id))
            fit = [o for o in same_file if o.path_id - e.path_id in near]
            if len(fit) == 1:
                e.status, e.target = BY_NAME, fit[0]
                e.candidates = [fit[0]] + [o for o in same_file if o is not fit[0]]
                e.how, e.count = HOW_NEIGHBOURS, len(same_file)
            else:
                e.status, e.candidates = AMBIGUOUS, _nearest(same_file, e.path_id, shifts(e.source, e.path_id))
                e.how, e.count = HOW_SEVERAL, len(same_file)
        elif len(cands) == 1:
            e.status, e.target, e.candidates = BY_NAME, cands[0][0], [cands[0][0]]
            e.how = HOW_OTHER_FILE
        elif cands:
            e.status, e.candidates = AMBIGUOUS, [o for o, _s in cands][:MAX_PICK_CANDIDATES]
            e.how, e.count = HOW_SEVERAL, len(cands)
        else:
            e.status = LOST
            script = e.declared.split(".", 1)[0] if "." in e.declared else ""
            if script and index.scripts.get(script):
                e.candidates = _nearest([o for _p, o, _n in index.kin(e.source, e)], e.path_id,
                                        shifts(e.source, e.path_id))
                e.how = HOW_SAME_SCRIPT
            else:
                e.how = HOW_NO_NAME
    for e in later:
        fit = []
        for shift in set(shifts(e.source, e.path_id)):
            there = index.slot.get((e.source, e.path_id + shift))
            if there is not None and there[1] == e.declared and _fits(there[0], e):
                fit.append((shift, there[0]))
        if len(fit) == 1 and fit[0][0] == 0:
            e.status, e.target, e.candidates, e.how = ON_SPOT, fit[0][1], [fit[0][1]], HOW_SPOT
        elif len(fit) == 1:
            e.status, e.target, e.candidates = BY_NAME, fit[0][1], [fit[0][1]]
            e.how = HOW_NAMELESS_NEIGHBOURS
        else:
            e.status = NAMELESS
            e.candidates = _nearest([o for _p, o, _n in index.kin(e.source, e)], e.path_id,
                                    shifts(e.source, e.path_id))
            e.how = HOW_NAMELESS_UNPLACED
    _drop_double_claims(entries)


def _nearest(objs, old_pid: int, shifts) -> list:
    """Up to MAX_PICK_CANDIDATES objects, nearest first to where the neighbours' shift says the patch went."""
    expected = old_pid + (shifts[0] if shifts else 0)
    return sorted(objs, key=lambda o: abs(o.path_id - expected))[:MAX_PICK_CANDIDATES]


def _claim_key(e: PatchEntry, obj):
    # One object may have a .png AND a .dump.json patch; two patches of the same kind may not share it.
    return id(obj), e.tail.lower()


def _drop_double_claims(entries: List[PatchEntry]) -> None:
    claims = Counter(_claim_key(e, e.target) for e in entries if e.target is not None)
    for e in entries:
        if e.target is not None and e.status != ON_SPOT and claims[_claim_key(e, e.target)] > 1:
            n = claims[_claim_key(e, e.target)]
            e.status, e.target = AMBIGUOUS, None
            e.how, e.count = HOW_CLAIMED, n


# ---------------------------------------------------------------------------------------------- writing copies



def _is_pptr(v) -> bool:
    return isinstance(v, dict) and "m_PathID" in v and "m_FileID" in v and len(v) == 2


@dataclass
class MergeNotes:
    added: List[str] = field(default_factory=list)       # fields the new build has and the patch did not
    removed: List[str] = field(default_factory=list)     # fields of the patch the new build no longer has
    references: int = 0                                  # references taken from the new object


def merge_dump(patch, new, notes: MergeNotes, where: str = ""):
    """The patch's dump moved onto the new object, in export-JSON form (what build_export_json writes):
    references are taken from the new object, every other value from the patch. The field set becomes the new
    object's (the import refuses anything else): a field the update added is filled from the new object, one it
    removed is dropped."""
    if _is_pptr(patch) and _is_pptr(new):
        if patch != new:
            notes.references += 1
        return new
    if isinstance(patch, dict) and isinstance(new, dict):
        out = {}
        for k, v in new.items():
            sub = f"{where}.{k}" if where else k
            if k in patch:
                out[k] = merge_dump(patch[k], v, notes, sub)
            else:
                out[k] = v
                notes.added.append(sub)
        for k in patch:
            if k not in new:
                notes.removed.append(f"{where}.{k}" if where else k)
        return out
    if isinstance(patch, list) and isinstance(new, list) and len(patch) == len(new):
        return [merge_dump(p, n, notes, f"{where}[{i}]") for i, (p, n) in enumerate(zip(patch, new))]
    return patch


def _export_json(obj):
    """obj in export-JSON form (what a .dump.json holds); None when it cannot be read in full."""
    from .object_dump import build_export_json
    text, _err, partial = build_export_json(obj)
    if text is None or partial:
        return None
    return json.loads(text)


def _read_json(path: Path):
    return json.loads(path.read_bytes().decode("utf-8-sig", errors="surrogateescape"))


def _dump_text(data) -> bytes:
    return json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8", errors="surrogateescape")


def rewrite_raw_head(patch: bytes, new: bytes, ptr_size: int) -> Tuple[bytes, int]:
    """A MonoBehaviour's Raw dump: its GameObject and script pointers (the fixed head: PPtr, UInt8 + padding,
    PPtr) taken from the new object. Returns (bytes, pointers replaced)."""
    out = bytearray(patch)
    replaced = 0
    for start in (0, ptr_size + 4):
        end = start + ptr_size
        if len(patch) < end or len(new) < end:
            continue
        if out[start:end] != new[start:end]:
            out[start:end] = new[start:end]
            replaced += 1
    return bytes(out), replaced


@dataclass
class WrittenFile:
    entry: PatchEntry
    dest: Path
    notes: List[str] = field(default_factory=list)
    new_path_id: Optional[int] = None    # the object it was written for (for the report)
    new_source: str = ""


@dataclass
class WriteResult:
    folder: Path
    written: List[WrittenFile] = field(default_factory=list)
    left_out: List[PatchEntry] = field(default_factory=list)
    problems: List[Tuple[PatchEntry, str]] = field(default_factory=list)
    report: Optional[Path] = None

    @property
    def rewritten(self) -> int:
        return sum(1 for w in self.written if w.notes)


def output_folder_problem(folder) -> Optional[str]:
    """A reason the copies cannot go to `folder`, or None (it must be new or empty)."""
    folder = Path(folder)
    if folder.exists() and not folder.is_dir():
        return tr("Это файл, а не папка.")
    if folder.is_dir() and any(folder.iterdir()):
        return tr("Папка не пустая. Выберите новую или пустую папку.")
    return None


def write_copies(entries: List[PatchEntry], out_dir, patch_folder=None, should_cancel: CancelCheck = None,
                 progress: Progress = None) -> WriteResult:
    """Writes every patch with a final target (on the spot, or accepted) into `out_dir` under its new name, in
    the same subfolders; the rest is listed in REPORT_NAME there. The patch folder itself is never written."""
    out_dir = Path(out_dir)
    problem = output_folder_problem(out_dir)
    if problem:
        raise ValueError(problem)
    if patch_folder is not None and _inside(out_dir, Path(patch_folder)):
        raise ValueError(tr("Новая папка не может быть внутри папки с патчами."))
    out_dir.mkdir(parents=True, exist_ok=True)
    result = WriteResult(out_dir)
    targets = [(e, e.final_target()) for e in entries]
    total = len(targets)
    used = set()
    for i, (e, obj) in enumerate(targets):
        if should_cancel and should_cancel():
            from .progress import OperationCancelled
            raise OperationCancelled()
        if progress and i % 50 == 0:
            progress(tr("Запись копий…"), i, total)
        if obj is None:
            result.left_out.append(e)
            continue
        try:
            dest = out_dir / e.rel.parent / new_file_name(e, obj)
            key = os.path.normcase(str(dest))
            if key in used:
                result.problems.append((e, tr("под этим именем уже записан другой патч")))
                continue
            used.add(key)
            dest.parent.mkdir(parents=True, exist_ok=True)
            notes = _write_one(e, obj, dest)
            result.written.append(WrittenFile(e, dest, notes, obj.path_id,
                                              sanitize_export_filename(str(obj.assets_file.name), fallback="unknown")))
        except Exception as ex:
            logger.debug("writing %s failed", e.path, exc_info=True)
            result.problems.append((e, str(ex) or type(ex).__name__))
    if progress:
        progress(tr("Запись копий…"), total, total)
    result.report = out_dir / REPORT_NAME
    result.report.write_text(report_text(result), encoding="utf-8")
    return result


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def _write_one(e: PatchEntry, obj, dest: Path) -> List[str]:
    """Writes one copy; returns what was changed in it (empty: copied as it is)."""
    if e.mode == "json_dump":
        patch = _read_json(e.path)
        new = _export_json(obj)
        if new is None:
            return _write_head_only(e, obj, patch, dest)
        notes = MergeNotes()
        merged = merge_dump(patch, new, notes)
        if merged == patch:
            shutil.copyfile(e.path, dest)
            return []
        dest.write_bytes(_dump_text(merged))
        return _note_lines(notes)
    if e.mode == "raw" and obj.type.name == "MonoBehaviour":
        patch = e.path.read_bytes()
        ptr = 12 if obj.assets_file.header.version >= 14 else 8
        data, replaced = rewrite_raw_head(patch, bytes(obj.get_raw_data()), ptr)
        if not replaced:
            shutil.copyfile(e.path, dest)
            return []
        dest.write_bytes(data)
        return [tr("ссылки на объект и скрипт взяты из новой версии ({replaced})", replaced=replaced)]
    shutil.copyfile(e.path, dest)
    return []


_HEAD_POINTERS = ("m_GameObject", "m_Script")


def _write_head_only(e: PatchEntry, obj, patch, dest: Path) -> List[str]:
    """The new object cannot be read in full (an IL2CPP layout that does not fit): only the pointers every
    MonoBehaviour starts with - read without a layout - are taken from it."""
    note = (tr("объект в новой версии игры прочитан не полностью, поэтому обновлены только ссылки на игровой "
       "объект и скрипт; функция импорта может отклонить такой патч"))
    try:
        new_head = obj.peek_dict(_HEAD_POINTERS) or {}
    except Exception:
        new_head = {}
    replaced = 0
    if isinstance(patch, dict):
        for key in _HEAD_POINTERS:
            mine, theirs = patch.get(key), new_head.get(key)
            if not (_is_pptr(mine) and isinstance(theirs, dict)):
                continue
            theirs = {"m_FileID": int(theirs.get("m_FileID", 0)), "m_PathID": int(theirs.get("m_PathID", 0))}
            if mine != theirs:
                patch[key] = theirs
                replaced += 1
    if not replaced:
        shutil.copyfile(e.path, dest)
        return [tr("объект в новой версии игры прочитан не полностью; функция импорта может отклонить такой патч")]
    dest.write_bytes(_dump_text(patch))
    return [note]


_ROUTINE_NOTE = N_("ссылки на другие объекты взяты из новой версии игры")


def _note_lines(notes: MergeNotes) -> List[str]:
    lines = []
    if notes.references:
        lines.append(f"{tr(_ROUTINE_NOTE)} ({notes.references})")
    if notes.added:
        lines.append(tr("добавлены поля, которые появились в новой версии: {fields}", fields=_few(notes.added)))
    if notes.removed:
        lines.append(tr("удалены поля, которых в новой версии нет: {fields}", fields=_few(notes.removed)))
    return lines


def _few(items: List[str], n: int = 5) -> str:
    shown = ", ".join(f"«{x}»" for x in items[:n])
    return shown + (" " + tr("и ещё {count}", count=len(items) - n) if len(items) > n else "")


_CAB_HASH = re.compile(r"^(CAB-[0-9a-f]{6})[0-9a-f]{26}(?:\.(.+))?$", re.IGNORECASE)
_NAME_WIDTH = 48          # a longer name is cut with «…» so the columns stay aligned


def short_source(source: str) -> str:
    """A file name as the report shows it: a bundle's CAB hash cut to its first characters
    («CAB-175f8e9ddd7a2e7379cc92cdbd02773b.sharedAssets» -> «CAB-175f8e… sharedAssets»)."""
    m = _CAB_HASH.match(source)
    if not m:
        return source
    return f"{m.group(1)}…" + (f" {m.group(2)}" if m.group(2) else "")


def display_name(declared: str) -> str:
    """The name part of a patch's file name, readable: «Script.Unnamed» -> «Script», «Script._GameObject_ Name»
    (a component named after its GameObject) -> «Script: Name»."""
    if declared.endswith(".Unnamed"):
        return declared[:-len(".Unnamed")]
    script, sep, rest = declared.partition("._GameObject_ ")
    if sep:
        return f"{script}: {rest}"
    return declared


def _cut(text: str, width: int) -> str:
    return text if len(text) <= width else text[:width - 1] + "…"


def _table(rows: List[Tuple[str, ...]], indent: str = "  ") -> List[str]:
    """Rows of columns, each column padded to its widest cell (the last one is not padded)."""
    if not rows:
        return []
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]) - 1)]
    return [indent + "   ".join([c.ljust(w) for c, w in zip(r, widths)] + [r[-1]]).rstrip() for r in rows]


def _group(entries, key):
    """[(group, items)] in first-seen order."""
    groups: Dict[str, list] = {}
    for item in entries:
        groups.setdefault(key(item), []).append(item)
    return list(groups.items())


def _folder(e: PatchEntry) -> str:
    """The patch's own folder name (an export's type folder: «MonoBehaviour», «Texture2D»), "" at the top."""
    return e.rel.parent.name


def _left_out_reason(e: PatchEntry) -> str:
    return (tr("Снята отметка") if e.decision == "skip" else
            tr("Вариант не выбран") if e.state == "choose" else
            tr("Несколько одинаковых объектов, невозможно определить нужный") if e.how == HOW_CANT_TELL else
            tr("В новой версии нет объекта с таким именем"))


def report_text(result: WriteResult) -> str:
    """The report: totals, the new numbers by folder, notes, then what was not moved grouped by reason. Names are
    readable (display_name) and bundle hashes cut (short_source); columns are aligned for a monospace font."""
    left = len(result.left_out) + len(result.problems)
    lines = [tr("Перенос патчей на новую версию игры"), "", tr("Сохранено: {count} • Не перенесено: {left}", count=len(result.written), left=left)]
    renamed = [w for w in result.written if w.dest.name != w.entry.path.name]
    unchanged = len(result.written) - len(renamed)
    if unchanged:
        lines[-1] += " • " + tr("Без изменений: {unchanged}", unchanged=unchanged)
    lines.append("")

    if renamed:
        lines += [tr("Новые номера ({count})", count=len(renamed)), ""]
        for folder, items in _group(renamed, lambda w: _folder(w.entry)):
            if folder:
                lines.append(folder)
            rows = []
            old_width = max(len(f"#{w.entry.path_id}") for w in items)
            for w in items:
                e = w.entry
                old_src, new_src = short_source(e.source), short_source(w.new_source or e.source)
                where = old_src if old_src == new_src else f"{old_src} → {new_src}"
                rows.append((_cut(display_name(e.declared), _NAME_WIDTH), f"#{e.path_id}".ljust(old_width) + f" → #{w.new_path_id}", where))
            lines += _table(rows)
            lines.append("")

    # every moved dump gets the new references - only the other notes are worth a line per file
    unusual = [(w, [n for n in w.notes if not n.startswith(tr(_ROUTINE_NOTE))]) for w in result.written]
    unusual = [(w, notes) for w, notes in unusual if notes]
    if unusual:
        lines += [tr("Обратите внимание ({count})", count=len(unusual)), ""]
        for w, notes in unusual:
            lines.append(f"  {display_name(w.entry.declared)} #{w.new_path_id} ({short_source(w.new_source)})")
            lines += [f"    {note}" for note in notes]
        lines.append("")

    if result.problems:
        lines += [tr("Не удалось сохранить ({count})", count=len(result.problems)), ""]
        lines += _table([(_cut(display_name(e.declared), _NAME_WIDTH), f"#{e.path_id}", short_source(e.source), why)
                         for e, why in result.problems])
        lines.append("")

    if result.left_out:
        lines += [tr("Не перенесено ({count})", count=len(result.left_out)), ""]
        groups = _group(result.left_out, _left_out_reason)
        rows_of = {reason: [(_cut(display_name(e.declared), _NAME_WIDTH), _folder(e), f"#{e.path_id}",
                             short_source(e.source)) for e in items] for reason, items in groups}
        aligned = iter(_table([r for _reason, rows in rows_of.items() for r in rows]))   # one alignment for all
        for reason, items in groups:
            lines.append(f"{reason} ({len(items)})")
            lines += [next(aligned) for _ in items]
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------------------------- comparing


def _leaves(value, where: str, out: Dict[str, Any], limit: int, strings: Optional[set] = None) -> None:
    """Every leaf of an export-JSON value as path -> text. strings: filled with the paths whose value is a string."""
    if len(out) >= limit:
        return
    if _is_pptr(value):
        out[where] = f"#{value['m_PathID']}" + (" " + tr("(файл {file_id})", file_id=value['m_FileID']) if value["m_FileID"] else "")
    elif isinstance(value, dict) and value:
        for k, v in value.items():
            _leaves(v, f"{where}.{k}" if where else k, out, limit, strings)
    elif isinstance(value, list) and value and not all(isinstance(x, (int, float)) for x in value):
        for i, v in enumerate(value):
            _leaves(v, f"{where}[{i}]", out, limit, strings)
    else:
        if isinstance(value, str) and strings is not None:
            strings.add(where)
        text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
        out[where] = text if len(text) <= 300 else text[:300] + "…"


def field_label(path: str) -> str:
    """A field path as the window shows it: «m_ParamDesc.ParamName» -> «ParamDesc › ParamName»,
    «Phrases[0].m_Text» -> «Phrases[0] › Text»."""
    parts = []
    for part in path.split("."):
        if part.startswith("m_") and len(part) > 2 and part[2].isalpha():
            part = part[2:]
        parts.append(part)
    return " › ".join(parts)


def _is_prose(value: Optional[str]) -> bool:
    """A string a person reads (a translation, a caption), not an identifier («Zvedac_Pan», «vrtak»): it has a
    space or a letter outside ASCII."""
    return bool(value) and any(c.isspace() or (ord(c) > 127 and c.isalpha()) for c in value)


def export_json_of(obj):
    """An object's export-JSON dict (None when it cannot be read in full) - for comparing."""
    try:
        return _export_json(obj)
    except Exception:
        return None


def patch_json_of(entry: PatchEntry):
    if entry.mode != "json_dump":
        return None
    try:
        return _read_json(entry.path)
    except Exception:
        return None


# ---------------------------------------------------------------------------------------------- the patch itself as evidence
#
# A patch carries the object it was made from: a .dump.json every field (a mod changes a few - texts, a size), a
# picture its pixels (a mod repaints a part). So the patch alone confirms a proposal; no old build is needed.

SAME, SIMILAR, DIFFERENT = "same", "similar", "different"
SIMILAR_FIELDS = 0.8          # share of equal fields from which a dump is "similar"
SIMILAR_PIXELS = 0.5          # share of (nearly) equal pixels from which a picture is "similar"
_PIXEL_TOLERANCE = 8          # per channel: the export's PNG round trip and premultiplied alpha move a pixel a little


@dataclass
class Match:
    """How a patch compares with one object."""
    verdict: str = ""         # SAME | SIMILAR | DIFFERENT | "" (cannot be compared)
    score: float = 0.0        # share of equal fields / pixels
    equal: int = 0
    total: int = 0
    differing: List["FieldDifference"] = field(default_factory=list)   # texts first, then the rest
    note: str = ""            # a plain sentence for the window

    @property
    def other_fields_differ(self) -> int:
        """How many fields other than texts differ: a mod mostly changes texts, so on the patch's own object
        these are usually none - several of them suggest another object of the same name."""
        return sum(1 for d in self.differing if not d.is_text)


@dataclass
class FieldDifference:
    path: str                       # as in the dump: «m_ParamDesc.ParamName»
    in_patch: Optional[str]         # None: the patch has no such field
    in_game: Optional[str]          # None: the object has no such field
    is_text: bool                   # a text a person reads (see _is_prose), on either side

    @property
    def label(self) -> str:
        return field_label(self.path)


def _comparable_leaves(data, strings: Optional[set] = None) -> Dict[str, str]:
    out: Dict[str, str] = {}
    _leaves(_blank_refs(data), "", out, 500000, strings)
    return out


# references and resource positions move in any rebuild; m_HashCode: a Phonopolis script field that is new in every
# build (205 of 213 differing "on the spot" MonoBehaviours differed in it, most in nothing else)
_VOLATILE = {"m_PathID", "m_FileID", "m_StreamData", "m_StreamingInfo", "m_Resource", "image data", "m_HashCode"}


def _blank_refs(value):
    if _is_pptr(value):
        return "#"                              # references move in any rebuild
    if isinstance(value, dict):
        return {k: (None if k in _VOLATILE else _blank_refs(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_blank_refs(v) for v in value]
    return value


def compare_dump(patch: dict, new: dict) -> Match:
    strings = set()
    mine, theirs = _comparable_leaves(patch, strings), _comparable_leaves(new, strings)
    keys = list(mine) + [k for k in theirs if k not in mine]
    equal = sum(1 for k in keys if k in mine and k in theirs and mine[k] == theirs[k])
    differing = [FieldDifference(k, mine.get(k), theirs.get(k),
                                 k in strings and (_is_prose(mine.get(k)) or _is_prose(theirs.get(k))))
                 for k in keys if mine.get(k) != theirs.get(k)]
    differing.sort(key=lambda d: not d.is_text)          # stable: texts first, each group in field order
    score = equal / max(len(keys), 1)
    verdict = SAME if equal == len(keys) else SIMILAR if score >= SIMILAR_FIELDS else DIFFERENT
    note = tr("Совпадение 100%") if verdict == SAME else tr("Совпадение {percent}", percent=_percent(score))
    return Match(verdict, score, equal, len(keys), differing, note)


def _percent(score: float) -> str:
    """A share as the window shows it: never «100%» unless everything is equal, never «0%» unless nothing is."""
    value = round(score * 100)
    if value == 100 and score < 1:
        value = 99
    if value == 0 and score > 0:
        value = 1
    return f"{value}%"


def compare_pictures(patch_image, game_image) -> Match:
    import numpy as np
    if patch_image.size != game_image.size:
        return Match("", 0.0, note=(tr("Другой размер картинки: {width} × {height} и {width2} × {height2}", width=patch_image.width, height=patch_image.height, width2=game_image.width, height2=game_image.height)))
    a = np.asarray(patch_image.convert("RGBA"), dtype=np.int16)
    b = np.asarray(game_image.convert("RGBA"), dtype=np.int16)
    # fully transparent pixels count as equal whatever colour they keep
    close = (np.abs(a - b).max(axis=2) <= _PIXEL_TOLERANCE) | ((a[..., 3] == 0) & (b[..., 3] == 0))
    total = int(close.size)
    equal = int(close.sum())
    score = equal / max(total, 1)
    verdict = SAME if score >= 0.999 else SIMILAR if score >= SIMILAR_PIXELS else DIFFERENT
    note = tr("Совпадение 100%") if verdict == SAME else tr("Совпадение {percent}", percent=_percent(score))
    return Match(verdict, score, equal, total, [], note)


def game_picture(obj):
    """What a Texture2D / Sprite export writes as its picture (PIL), or None."""
    if obj is None or obj.type.name not in ("Texture2D", "Sprite"):
        return None
    try:
        return obj.read().image
    except Exception:
        return None


def patch_picture(entry: PatchEntry):
    if entry.path.suffix.lower() != ".png":
        return None
    try:
        from PIL import Image
        with Image.open(entry.path) as im:
            return im.convert("RGBA")
    except Exception:
        return None


_MISSING = object()


class _PatchData:
    """A patch's content read once (dump JSON / picture), for comparing with several objects."""

    def __init__(self, entry: PatchEntry):
        self.entry = entry
        self._dump = _MISSING
        self._picture = _MISSING

    def dump(self):
        if self._dump is _MISSING:
            self._dump = patch_json_of(self.entry)
        return self._dump

    def picture(self):
        if self._picture is _MISSING:
            self._picture = patch_picture(self.entry)
        return self._picture


def can_compare(entry: PatchEntry) -> bool:
    return entry.mode == "json_dump" or entry.path.suffix.lower() == ".png"


def compare_patch(entry: PatchEntry, obj, data: Optional[_PatchData] = None) -> Match:
    """The patch's own content against `obj`."""
    data = data or _PatchData(entry)
    if obj is None:
        return Match()
    if entry.mode == "json_dump":
        patch = data.dump()
        if not isinstance(patch, dict):
            return Match(note=tr("Не удалось прочитать патч"))
        new = export_json_of(obj)
        if new is None:
            return Match(note=tr("Объект в игре читается не полностью — сравнить нельзя"))
        return compare_dump(patch, new)
    if entry.path.suffix.lower() == ".png":
        picture = data.picture()
        if picture is None:
            return Match(note=tr("Не удалось прочитать картинку патча"))
        game = game_picture(obj)
        if game is None:
            return Match(note=tr("Не удалось прочитать картинку в игре"))
        return compare_pictures(picture, game)
    return Match(note=tr("Сравнивается только по имени"))


def rank_candidates(entry: PatchEntry, should_cancel: CancelCheck = None) -> List[Tuple[Any, Match]]:
    """The patch's candidates with how each compares with the patch's own content, best first (same, then similar,
    by share; ties keep the neighbours' order). Content does NOT decide alone: measured on 1,500 real Phonopolis
    dumps the right object was "same" in 99.5 %, but another object of the same script was "same" too in a third
    of the cases (identical components) and "similar" from 92 % - so it orders the variants, the user picks."""
    data = _PatchData(entry)
    scored = []
    for order, obj in enumerate(entry.candidates):
        if should_cancel and should_cancel():
            break
        scored.append((order, obj, compare_patch(entry, obj, data)))
    rank = {SAME: 0, SIMILAR: 1, "": 2, DIFFERENT: 3}
    scored.sort(key=lambda t: (rank.get(t[2].verdict, 2), -t[2].score, t[0]))
    return [(obj, m) for _o, obj, m in scored]


# how much better than the next candidate the content must match to decide (0.03 and 0.05 placed the
# same 506 of 2,587 real Phonopolis ties with every text changed, all right)
CLEAR_MARGIN = 0.03
# nameless too: 2,191 of 3,198 real nameless Phonopolis dumps placed (1,012 with every text changed), all right
SETTLED_STATUSES = (AMBIGUOUS, NAMELESS)


def settle_by_content(entries: List[PatchEntry], should_cancel: CancelCheck = None, progress: Progress = None) -> int:
    """A patch several same-named objects fit (AMBIGUOUS: a folder too sparse for the neighbours' shift), or a
    nameless one no neighbour places (NAMELESS: its candidates are the nearest objects of its kind), is placed
    by its own content when exactly ONE candidate matches it clearly best: the only one with the same content, or
    - a mod changed some fields - the only similar one ahead of the next by CLEAR_MARGIN. Identical objects stay
    for the user. Returns how many were placed."""
    todo = [e for e in entries if e.status in SETTLED_STATUSES and len(e.candidates) > 1 and can_compare(e)]
    placed = 0
    for i, e in enumerate(todo):
        if should_cancel and should_cancel():
            from .progress import OperationCancelled
            raise OperationCancelled()
        if progress and i % 20 == 0:
            progress(tr("Сравнение с содержимым патчей…"), i, len(todo))
        ranked = rank_candidates(e, should_cancel)
        if not ranked:
            continue
        e.candidates = [o for o, _m in ranked]
        best_o, best = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else None
        same = sum(1 for _o, m in ranked if m.verdict == SAME)
        if same > 1:
            e.how, e.count = HOW_IDENTICAL, same
            continue
        if best.verdict == SAME and same == 1:
            pass
        elif (best.verdict == SIMILAR and same == 0
              and (second is None or best.score - second.score >= CLEAR_MARGIN)):
            pass
        else:
            continue
        e.status, e.target = BY_NAME, best_o
        e.how, e.count = HOW_CONTENT, len(ranked)
        placed += 1
    _drop_double_claims(entries)
    return placed


def is_picture(entry: PatchEntry) -> bool:
    """A patch the user can judge by eye (a picture next to the object's picture)."""
    return entry.path.suffix.lower() == ".png"


def _prose_of(data) -> Dict[str, str]:
    """The texts a person reads in an export-JSON dump (see _is_prose), by field path."""
    leaves: Dict[str, str] = {}
    strings: set = set()
    _leaves(_blank_refs(data), "", leaves, 500000, strings)
    return {k: v for k, v in leaves.items() if k in strings and _is_prose(v)}


def _first_text(texts: Dict[str, str], paths) -> str:
    return next((texts[k] for k in paths if texts.get(k)), "")


# measured on the Phonopolis update (77k real dumps): of 3,301 still to choose after settle_by_content, 3,178 had
# no text at all in the patch and ~100 had texts that tell the candidates apart; checking them all took 5 s
def drop_guesses(entries: List[PatchEntry], should_cancel: CancelCheck = None, progress: Progress = None) -> int:
    """A dump still to choose for keeps its candidates only when a person can tell them apart: its own text and
    the candidates' texts in the game, at least two of them different. Otherwise the choice would be a guess
    among technical fields - the patch is not offered (state "lost", how HOW_CANT_TELL; a nameless or same-script
    one keeps its own how). Pictures keep their candidates: the window shows them side by side.
    Returns how many were dropped."""
    todo = [e for e in entries if e.state == "choose" and not is_picture(e)]
    dropped = 0
    for i, e in enumerate(todo):
        if should_cancel and should_cancel():
            from .progress import OperationCancelled
            raise OperationCancelled()
        if progress and i % 50 == 0:
            progress(tr("Проверка текстов…"), i, len(todo))
        texts = {}
        mine = _prose_of(patch_json_of(e)) if e.how not in (HOW_SAME_SCRIPT, HOW_NAMELESS_UNPLACED) else {}
        if mine:
            for obj in e.candidates:
                theirs = _prose_of(export_json_of(obj) or {})
                texts[id(obj)] = _first_text(theirs, mine)
        if len({t for t in texts.values() if t}) >= 2:
            e.patch_text, e.candidate_texts = _first_text(mine, mine), texts
            continue
        if e.how not in (HOW_SAME_SCRIPT, HOW_NAMELESS_UNPLACED):
            e.how, e.count = HOW_CANT_TELL, len(e.candidates)
        e.candidates = []
        dropped += 1
    return dropped
