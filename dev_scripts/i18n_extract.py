"""Keeps UStudio/locales/*.json in step with the texts in the code (core/i18n.py explains the system).

    python dev_scripts/i18n_extract.py               # report: missing / untranslated / unused keys, problems
    python dev_scripts/i18n_extract.py --update      # also add every new key to each catalog (value null)
    python dev_scripts/i18n_extract.py --update --prune   # ... and drop keys no code uses any more
    python dev_scripts/i18n_extract.py --raw         # Russian literals NOT wrapped in tr()/N_() yet, per file
    python dev_scripts/i18n_extract.py --raw main.py # ... with lines, for the named files

Scanned: every .py under UStudio/ except the vendored UnityPy, UnityPyBoost, bundled_tools and the
command-line front end (cli/, ustudio_cli.py — English, not translated). core/ IS scanned: its messages are
shown by the GUI (and printed in English by the CLI).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "UStudio"
LOCALES = SRC / "locales"
sys.path.insert(0, str(SRC))

from core import i18n  # noqa: E402

EXCLUDED_DIRS = {"UnityPy", "UnityPyBoost", "bundled_tools", "cli", "__pycache__", "locales"}
EXCLUDED_FILES = {"ustudio_cli.py"}
# A line with this comment keeps its Russian literal on purpose (a language's own name, a sample text).
KEEP_MARK = "# i18n: keep"
CYRILLIC = re.compile("[А-Яа-яЁёІіЇїЄєҐґ]")

# Calls whose texts are not shown to the user (debug logs, exceptions for developers): their Russian literals
# are not counted by --raw.
_DEBUG_CALLS = {"debug"}


@dataclass
class Key:
    text: str
    ctx: Optional[str]
    plural: Optional[Tuple[str, str, str]] = None      # Russian one/few/many for trn()
    places: List[str] = field(default_factory=list)


@dataclass
class Scan:
    keys: Dict[Tuple[Optional[str], str], Key] = field(default_factory=dict)
    problems: List[str] = field(default_factory=list)
    raw: Dict[str, List[Tuple[int, str]]] = field(default_factory=dict)


def source_files(root: Path = SRC) -> Iterator[Path]:
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if rel.parts[0] in EXCLUDED_DIRS or any(p in EXCLUDED_DIRS for p in rel.parts[:-1]):
            continue
        if rel.name in EXCLUDED_FILES and len(rel.parts) == 1:
            continue
        yield path


def _literal(node) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _func_name(call: ast.Call) -> str:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def _kw(call: ast.Call, name: str):
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


# where the first text argument is: tr(text), N_(text), translate_to(code, text), trn(n, one, few, many)
_TEXT_ARG = {"tr": 0, "N_": 0, "translate_to": 1}


def _docstring_nodes(tree) -> set:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and _literal(body[0].value) is not None:
                out.add(id(body[0].value))
    return out


def scan_file(path: Path, scan: Scan, root: Path = SRC) -> None:
    rel = path.relative_to(root).as_posix()
    try:
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        scan.problems.append(f"{rel}: cannot parse: {e}")
        return
    wrapped: set = set()       # ids of literal nodes that are a key (or inside a debug call)

    def add(text, ctx, place, plural=None):
        k = scan.keys.get((ctx, text))
        if k is None:
            k = scan.keys[(ctx, text)] = Key(text, ctx, plural)
        elif plural is not None and k.plural is None or plural is None and k.plural is not None:
            scan.problems.append(f"{place}: «{text}» is used both as a plural (trn) and a plain text (tr)")
        k.places.append(place)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _func_name(node)
        place = f"{rel}:{node.lineno}"
        if name in _DEBUG_CALLS:
            for sub in ast.walk(node):
                wrapped.add(id(sub))
            continue
        if name not in _TEXT_ARG and name != "trn":
            continue
        if isinstance(node.func, ast.Attribute) and not (
                isinstance(node.func.value, ast.Name) and node.func.value.id == "i18n"):
            continue   # obj.tr(...) is Qt's QObject.tr, not ours; i18n.tr(...) is
        ctx_node = _kw(node, "ctx")
        ctx = None
        if ctx_node is not None:
            ctx = _literal(ctx_node)
            if ctx is None:
                scan.problems.append(f"{place}: ctx= must be a string literal")
                continue
            wrapped.add(id(ctx_node))
        if name == "trn":
            texts = node.args[1:4]
            values = [_literal(a) for a in texts]
            if len(texts) < 3 or any(v is None for v in values):
                scan.problems.append(f"{place}: trn() needs three string literals (one, few, many)")
                continue
            wrapped.update(id(a) for a in texts)
            add(values[0], ctx, place, tuple(values))
            continue
        index = _TEXT_ARG[name]
        if len(node.args) <= index:
            continue
        arg = node.args[index]
        text = _literal(arg)
        if text is None:
            if name != "N_":
                # tr(TABLE[kind]) of an N_() table is fine; f-strings and "+" are not
                if isinstance(arg, (ast.JoinedStr, ast.BinOp)) or (
                        isinstance(arg, ast.Call) and _func_name(arg) == "format"):
                    scan.problems.append(f"{place}: {name}() of a built string — use a literal with "
                                         f"{{placeholders}}")
            else:
                scan.problems.append(f"{place}: N_() needs a string literal")
            continue
        wrapped.add(id(arg))
        add(text, ctx, place)

    docstrings = _docstring_nodes(tree)
    lines = source.splitlines()
    raw = []
    for node in ast.walk(tree):
        if id(node) in wrapped or id(node) in docstrings:
            continue
        if hasattr(node, "lineno") and KEEP_MARK in lines[node.lineno - 1]:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and CYRILLIC.search(node.value):
            raw.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr) and id(node) not in wrapped:
            parts = "".join(v.value for v in node.values if isinstance(v, ast.Constant))
            if CYRILLIC.search(parts):
                raw.append((node.lineno, "f\"" + parts + "\""))
                for v in node.values:
                    wrapped.add(id(v))
    if raw:
        scan.raw[rel] = sorted(raw)


# --english: calls whose text argument the user sees. A Latin-letter literal (or f-string) passed straight to one of
# them, outside tr(), is a hard-coded English text (the Cyrillic scan above cannot see those).
_UI_CALLS = {
    "setText", "setToolTip", "setWindowTitle", "setPlaceholderText", "setStatusTip", "setTitle", "addTab",
    "addMenu", "addAction", "QAction", "QLabel", "QPushButton", "QCheckBox", "QRadioButton", "QGroupBox", "QMenu",
    "QToolButton", "information", "warning", "critical", "question", "log", "log_with_folder_link", "showMessage",
    "setItemText", "addItem", "insertItem", "show_notice", "show_text", "show_items", "setHorizontalHeaderLabels",
    "setHeaderLabels", "_make_item", "QTreeWidgetItem", "QListWidgetItem", "setLabelText", "getExistingDirectory",
    "getOpenFileName", "getOpenFileNames", "getSaveFileName", "wrap_tooltip", "set_elided_label_text",
}
_ENGLISH_WORD = re.compile(r"[A-Za-z]{3,}")
# Technical tokens that are fine untranslated (type names, formats, keys, file names...).
_NOT_PROSE = re.compile(r"^[\w.:/\\#%{}()\[\]<>=+*-]*$")


def _call_name(call: ast.Call) -> str:
    f = call.func
    return f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")


def english_literals(path: Path, root: Path = SRC) -> List[Tuple[int, str]]:
    """(line, text) of Latin-letter texts handed directly to a UI call, not through tr()."""
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    lines = source.split("\n")
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node) not in _UI_CALLS:
            continue
        for arg in list(node.args) + [k.value for k in node.keywords if k.arg in ("name", "text", "title")]:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                text = arg.value
            elif isinstance(arg, ast.JoinedStr):
                text = "".join(v.value for v in arg.values if isinstance(v, ast.Constant))
            else:
                continue
            if CYRILLIC.search(text) or not _ENGLISH_WORD.search(text) or _NOT_PROSE.match(text.strip()):
                continue
            if " " not in text.strip() and not text.strip()[:1].isupper():
                continue
            if KEEP_MARK in lines[arg.lineno - 1]:
                continue
            out.append((arg.lineno, text))
    return sorted(set(out))


def scan_sources(root: Path = SRC) -> Scan:
    scan = Scan()
    for path in source_files(root):
        scan_file(path, scan, root)
    return scan


# --- catalogs ---------------------------------------------------------------------------------------------------


def catalog_codes() -> List[str]:
    return [c for c in i18n.LANGUAGES if c != i18n.BASE_LANGUAGE]


def read_catalog(code: str) -> dict:
    path = LOCALES / f"{code}.json"
    if not path.is_file():
        return {"_meta": {"code": code, "name": i18n.LANGUAGE_NAMES.get(code, code), "fallback": []},
                "messages": {}, "contexts": {}}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_catalog(code: str, data: dict) -> None:
    LOCALES.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    (LOCALES / f"{code}.json").write_text(text, encoding="utf-8", newline="\n")


def _table(data: dict, ctx: Optional[str]) -> dict:
    if ctx is None:
        return data.setdefault("messages", {})
    return data.setdefault("contexts", {}).setdefault(ctx, {})


_PERCENT_SLOT = re.compile(r"%[sdirf]")


def _percent_slots(text: str) -> List[str]:
    """The %s / %d ... slots of a logging-style message, in order (a translation must keep the same ones)."""
    return _PERCENT_SLOT.findall(text)


def check_catalog(code: str, data: dict, scan: Scan) -> Tuple[List[str], List[str], List[str], List[str]]:
    """(missing keys, untranslated keys, unused keys, problems) of one catalog against the code."""
    missing, untranslated, unused, problems = [], [], [], []
    forms = i18n.PLURAL_FORM_COUNT.get(code, 2)
    for (ctx, text), key in scan.keys.items():
        table = (data.get("contexts") or {}).get(ctx, {}) if ctx else (data.get("messages") or {})
        label = f"[{ctx}] {text}" if ctx else text
        if text not in table:
            missing.append(label)
            continue
        value = table[text]
        if value is None or (isinstance(value, list) and not all(value)) or value == "":
            untranslated.append(label)
            continue
        if key.plural:
            if not isinstance(value, list):
                problems.append(f"{code}: «{label}» is a plural (trn) — its value must be a list of {forms} forms")
                continue
            if len(value) != forms:
                problems.append(f"{code}: «{label}» has {len(value)} plural forms, {code} needs {forms}")
            want = set().union(*(i18n.placeholders(t) for t in key.plural))
            for v in value:
                if i18n.placeholders(v) - want - {"n"}:
                    problems.append(f"{code}: «{label}» -> «{v}»: placeholders "
                                    f"{sorted(i18n.placeholders(v) - want)} are not in the Russian text")
        else:
            if not isinstance(value, str):
                problems.append(f"{code}: «{label}» must be a text, not {type(value).__name__}")
                continue
            if i18n.placeholders(value) != i18n.placeholders(text):
                problems.append(f"{code}: «{label}» -> «{value}»: placeholders {sorted(i18n.placeholders(value))}"
                                f" differ from the Russian {sorted(i18n.placeholders(text))}")
            if _percent_slots(value) != _percent_slots(text):
                problems.append(f"{code}: «{label}» -> «{value}»: %-slots {_percent_slots(value)} differ from the "
                                f"Russian {_percent_slots(text)} (log messages are formatted with %)")
    used = set(scan.keys)
    for text in (data.get("messages") or {}):
        if (None, text) not in used:
            unused.append(text)
    for ctx, table in (data.get("contexts") or {}).items():
        for text in table:
            if (ctx, text) not in used:
                unused.append(f"[{ctx}] {text}")
    return missing, untranslated, unused, problems


def update_catalog(code: str, data: dict, scan: Scan, prune: bool) -> int:
    added = 0
    forms = i18n.PLURAL_FORM_COUNT.get(code, 2)
    for (ctx, text), key in scan.keys.items():
        table = _table(data, ctx)
        if text not in table:
            table[text] = [None] * forms if key.plural else None
            added += 1
    if prune:
        used = set(scan.keys)
        for text in list(data.get("messages") or {}):
            if (None, text) not in used:
                del data["messages"][text]
        for ctx, table in list((data.get("contexts") or {}).items()):
            for text in list(table):
                if (ctx, text) not in used:
                    del table[text]
            if not table:
                del data["contexts"][ctx]
    return added


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--update", action="store_true", help="add new keys to every catalog (null = to translate)")
    ap.add_argument("--prune", action="store_true", help="with --update: remove keys no code uses")
    ap.add_argument("--raw", nargs="*", metavar="FILE", help="Russian literals not wrapped yet (per file / lines)")
    ap.add_argument("--english", nargs="*", metavar="FILE",
                    help="Latin-letter texts handed to UI calls without tr() (hard-coded English)")
    args = ap.parse_args(argv)

    if args.english is not None:
        wanted = {Path(f).as_posix() for f in args.english}
        total = 0
        for path in source_files():
            rel = path.relative_to(SRC).as_posix()
            if wanted and rel not in wanted:
                continue
            found = english_literals(path)
            total += len(found)
            for line, text in found:
                print(f"{rel}:{line}: {text[:100]!r}")
        print(f"{total} hard-coded English texts")
        return 0

    scan = scan_sources()
    failed = bool(scan.problems)
    for p in scan.problems:
        print("PROBLEM", p)

    if args.raw is not None:
        wanted = {Path(f).as_posix() for f in args.raw}
        total = 0
        for rel, items in sorted(scan.raw.items(), key=lambda kv: -len(kv[1])):
            total += len(items)
            if wanted and rel not in wanted:
                continue
            print(f"{len(items):5}  {rel}")
            if wanted:
                for line, text in items:
                    print(f"         {line}: {text[:100]!r}")
        print(f"{total} Russian literals in {len(scan.raw)} files are not wrapped in tr()/N_() yet")
        return 1 if failed else 0

    print(f"{len(scan.keys)} texts in the code")
    for code in catalog_codes():
        data = read_catalog(code)
        if args.update:
            added = update_catalog(code, data, scan, args.prune)
            write_catalog(code, data)
            print(f"{code}: {added} new keys added")
        missing, untranslated, unused, problems = check_catalog(code, data, scan)
        print(f"{code}: missing {len(missing)}, untranslated {len(untranslated)}, unused {len(unused)}")
        for label in missing[:20]:
            print(f"   missing: {label}")
        for label in unused[:20]:
            print(f"   unused: {label}")
        for p in problems:
            print("PROBLEM", p)
        failed = failed or bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
