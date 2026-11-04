"""One-time (repeatable) source transform: splits UnityPy/classes/generated.py's
single ~12,000-line / ~890-class module into a package of several smaller modules.

Why: Nuitka compiles one C file per Python module. This single module compiled to
a C file large enough to make MSVC's cl.exe crash with "fatal error C1002: not
enough memory for pass 2" during a real UStudio --standalone build — confirmed to
persist even after upgrading to Nuitka 4.2.1 (whose main focus was exactly this
class of "C compilation scalability" problem, and which did fix two other
previously-crashing files, preview_panel.c and numpy.ma.core.c, just not this
one). Splitting the module into several smaller ones makes each individual
generated C file small enough for MSVC to compile, with zero behavioral change:
every class name is still importable exactly the same way
(`from UnityPy.classes.generated import X`), since the new package's __init__.py
re-exports everything the original module did.

Safe because:
- `from __future__ import annotations` (already present in the original file)
  means every type hint in every class body is stored as a string, never
  evaluated at class-definition time or anywhere else in this codebase
  (confirmed via a project-wide grep for get_type_hints/resolve_types — nothing
  calls either on these classes) — so classes can freely reference each other in
  annotations regardless of which submodule they end up living in.
- The only things that ARE evaluated live (and so must be real, already-defined
  objects at each class statement's exec time) are the `@unitypy_define`
  decorator and each class's actual base-class list. Both are handled here by
  generating the correct `from ._common import ...` / `from ._partNN import ...`
  imports per chunk, computed from the real AST, not guessed.
- No generated class has any method/property — confirmed via grep (the only
  `def` in the whole original file is `unitypy_define` itself) — so there is no
  other runtime code path that could depend on which module a class lives in.

Run with: python dev_scripts/split_generated_classes.py
Rerun this after any future upstream UnityPy update regenerates
classes/generated.py (see CLAUDE.md's "UnityPy vendored copy updated" section)
instead of re-doing this split by hand.
"""

import ast
import re
import shutil
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parent.parent
    / "UStudio"
    / "UnityPy"
    / "classes"
    / "generated.py"
)
PACKAGE_DIR = SOURCE.parent / "generated"
NUM_CHUNKS = 9
# Every generated class's real (non-annotation) base classes are either another
# generated class (handled generically below) or one of these two, imported at
# the top of the original file rather than defined in it.
COMMON_BASE_NAMES = {"Object", "ABC"}


def node_span(node: ast.ClassDef) -> tuple[int, int]:
    start = node.lineno
    if node.decorator_list:
        start = min(d.lineno for d in node.decorator_list)
    return start, node.end_lineno


def main() -> None:
    source_text = SOURCE.read_text(encoding="utf-8")
    lines = source_text.splitlines(keepends=True)

    def segment(start: int, end: int) -> str:
        return "".join(lines[start - 1 : end])

    tree = ast.parse(source_text, filename=str(SOURCE))
    class_nodes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    header_nodes = [n for n in tree.body if not isinstance(n, ast.ClassDef)]
    if not class_nodes:
        raise AssertionError("no classes found — did generated.py change shape?")

    first_class_start = node_span(class_nodes[0])[0]
    if any(n.lineno > first_class_start for n in header_nodes):
        raise AssertionError(
            "found top-level non-class code AFTER the first class — this "
            "script's assumption that all non-class code is a shared header "
            "no longer holds, needs a human look before rerunning"
        )

    names_seen = set()
    for node in class_nodes:
        if node.name in names_seen:
            raise AssertionError(f"duplicate top-level class name: {node.name!r}")
        names_seen.add(node.name)

    header_end = header_nodes[-1].end_lineno
    header_text = segment(1, header_end)
    # _common.py lives one directory deeper than the original generated.py did
    # (UnityPy/classes/generated.py -> UnityPy/classes/generated/_common.py), so
    # every single-dot relative import in the header (from .math import ...,
    # from .Object import Object, from .PPtr import PPtr) needs to become
    # double-dot to still reach UnityPy/classes/*.
    header_text = re.sub(r"^from \.(?=\w)", "from ..", header_text, flags=re.MULTILINE)

    spans = [node_span(n) for n in class_nodes]
    sizes = [end - start + 1 for start, end in spans]
    total_lines = sum(sizes)
    target = total_lines / NUM_CHUNKS

    chunks: list[list[ast.ClassDef]] = []
    current: list[ast.ClassDef] = []
    cumulative = 0
    next_threshold = target
    for node, size in zip(class_nodes, sizes):
        current.append(node)
        cumulative += size
        if cumulative >= next_threshold and len(chunks) < NUM_CHUNKS - 1:
            chunks.append(current)
            current = []
            next_threshold += target
    if current:
        chunks.append(current)

    name_to_chunk = {}
    for idx, chunk in enumerate(chunks):
        for node in chunk:
            name_to_chunk[node.name] = idx

    if PACKAGE_DIR.exists():
        shutil.rmtree(PACKAGE_DIR)
    PACKAGE_DIR.mkdir()

    (PACKAGE_DIR / "_common.py").write_text(header_text, encoding="utf-8")

    part_module_names = [f"_part{idx:02d}" for idx in range(len(chunks))]

    for idx, chunk in enumerate(chunks):
        needed_common: set[str] = set()
        needed_cross: dict[int, set[str]] = {}
        for node in chunk:
            needed_common.add("unitypy_define")
            for base in node.bases:
                if not isinstance(base, ast.Name):
                    raise AssertionError(
                        f"non-simple base on {node.name}: {ast.dump(base)}"
                    )
                bname = base.id
                if bname in COMMON_BASE_NAMES:
                    needed_common.add(bname)
                elif bname in name_to_chunk:
                    src_idx = name_to_chunk[bname]
                    if src_idx != idx:
                        needed_cross.setdefault(src_idx, set()).add(bname)
                    # else: defined earlier in this SAME chunk — no import needed
                else:
                    raise AssertionError(
                        f"unresolvable base {bname!r} on class {node.name}"
                    )

        out = ["# type: ignore\n", "from __future__ import annotations\n\n"]
        if needed_common:
            out.append(f"from ._common import {', '.join(sorted(needed_common))}\n")
        for src_idx in sorted(needed_cross):
            names = ", ".join(sorted(needed_cross[src_idx]))
            out.append(f"from .{part_module_names[src_idx]} import {names}\n")
        out.append("\n\n")
        for node in chunk:
            start, end = node_span(node)
            out.append(segment(start, end))
            out.append("\n\n")

        (PACKAGE_DIR / f"{part_module_names[idx]}.py").write_text(
            "".join(out), encoding="utf-8"
        )

    init_lines = ["# type: ignore\n", "from ._common import *  # noqa: F403\n"]
    init_lines += [f"from .{name} import *  # noqa: F403\n" for name in part_module_names]
    (PACKAGE_DIR / "__init__.py").write_text("".join(init_lines), encoding="utf-8")

    SOURCE.unlink()

    print(f"Split {len(class_nodes)} classes into {len(chunks)} parts under {PACKAGE_DIR}")
    size_by_id = {id(n): s for n, s in zip(class_nodes, sizes)}
    for idx, chunk in enumerate(chunks):
        part_lines = sum(size_by_id[id(n)] for n in chunk)
        print(f"  {part_module_names[idx]}.py: {len(chunk)} classes, ~{part_lines} source lines")


if __name__ == "__main__":
    main()
