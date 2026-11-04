"""Prepares a ready-to-use release: zips the portable GUI and CLI builds into <releases>/v<version>/.

    python prepare_release.py                  # both, into ..\\Релизы\\v<version>\\
    python prepare_release.py --only cli       # just one of them
    python prepare_release.py --out D:\\rel    # another releases folder (v<version> is made inside it)
    python prepare_release.py --overwrite      # replace zips that already exist (default: refuse)

Run it AFTER build_GUI_portable.py / "build_CLI_portable (one file).py" (one at a time, see CLAUDE.md). It takes
what is in dist\\UStudio and dist-cli\\ and produces

    UStudio GUI v<version>.zip   one root folder "UStudio v<version>" with the whole standalone build
    UStudio CLI v<version>.zip   flat: ustudio_cli.exe + the docs the CLI build copied next to it

Checks (an error stops that zip, nothing is written):
  * the exe's embedded FileVersion equals APP_VERSION in UStudio/app_info.py (a stale build of an older version);
  * the GUI build contains every native tool/DLL that exists in UStudio/UnityPy/resources (a missing msdf-atlas-gen.exe
    once went unnoticed because Nuitka drops such files silently);
  * the docs listed in the build scripts (CLI_DOCS / GUI_DOCS) are present;
  * both builds carry LICENSE.txt and THIRD-PARTY.txt, the latter with the source link (GPL: a release must say
    where its source is) — so SOURCE_URL in UStudio/app_info.py must be set before the builds are made.
Warnings (printed, not fatal): sources changed after the build was made (so the build may not contain them).

Repository/editor leftovers (.git, .vscode, .gitattributes, *.backup, __pycache__, *.pyc) are never zipped, even if
a build still has them. The build folders themselves are not modified. After zipping, every zip is tested and its
files are compared byte for byte with the build, then the SHA-256 of each zip is printed."""

import argparse
import ctypes
import hashlib
import importlib.util
import re
import sys
import zipfile
from ctypes import wintypes
from pathlib import Path
from typing import Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / "UStudio"
GUI_BUILD = ROOT / "dist" / "UStudio"
CLI_BUILD = ROOT / "dist-cli"
DEFAULT_RELEASES = ROOT.parent / "Релизы"

_JUNK_DIRS = {".git", ".vscode", "__pycache__"}
_JUNK_NAMES = {".gitattributes", ".gitignore"}
_JUNK_SUFFIXES = (".pyc", ".backup")


class ReleaseError(Exception):
    pass


def read_version() -> str:
    text = (APP_DIR / "app_info.py").read_text(encoding="utf-8")
    m = re.search(r'^APP_VERSION\s*=\s*"(\d+\.\d+\.\d+)"', text, flags=re.M)
    if not m:
        raise ReleaseError("APP_VERSION = \"x.y.z\" not found in UStudio/app_info.py")
    return m.group(1)


def exe_file_version(path: Path) -> Optional[str]:
    """The embedded 4-part FileVersion of a Windows exe ("1.2.0.0"), or None if it has none."""
    version = ctypes.WinDLL("version", use_last_error=True)
    size = version.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return None
    buf = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, buf):
        return None
    ptr = ctypes.c_void_p()
    length = wintypes.UINT()
    if not version.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)) or not ptr.value:
        return None
    info = (wintypes.DWORD * 4).from_address(ptr.value + 8)      # dwFileVersionMS, dwFileVersionLS follow 8 bytes
    ms, ls = info[0], info[1]
    return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"


def is_junk(rel_posix: str) -> bool:
    parts = rel_posix.split("/")
    return (any(p in _JUNK_DIRS for p in parts) or parts[-1] in _JUNK_NAMES
            or parts[-1].endswith(_JUNK_SUFFIXES))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _uses_qt(path: Path) -> bool:
    try:
        return path.suffix == ".py" and "PyQt6" in path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def sources_newer_than(build_exe: Path, limit: int = 5, skip_qt: bool = False) -> List[str]:
    """Source files changed after the build was made (newest first, at most `limit`). `skip_qt`: ignore modules that
    import PyQt6 — the CLI build excludes PyQt6, so a GUI-only change cannot be missing from it."""
    built = build_exe.stat().st_mtime
    newer = []
    for base in (APP_DIR, ROOT / "docs" / "ru"):
        for path in base.rglob("*"):
            rel = path.relative_to(ROOT).as_posix()
            if not path.is_file() or is_junk(rel) or "dummy_not_used" in rel or "UStudio_Packed" in rel:
                continue
            if path.suffix not in (".py", ".md", ".txt", ".yml", ".json", ".pyd", ".dll", ".exe"):
                continue
            if skip_qt and _uses_qt(path):
                continue
            if path.stat().st_mtime > built + 1:
                newer.append((path.stat().st_mtime, rel))
    return [rel for _t, rel in sorted(newer, reverse=True)[:limit]]


def native_resources() -> List[str]:
    """Files under UStudio/UnityPy/resources and UStudio/bundled_tools that the GUI build must carry (everything but
    Python/cache)."""
    out = []
    for base in (APP_DIR / "UnityPy" / "resources", APP_DIR / "bundled_tools"):
        for path in base.rglob("*"):
            rel = path.relative_to(APP_DIR).as_posix()
            if path.is_file() and not is_junk(rel) and path.suffix != ".py":
                out.append(rel)
    return sorted(out)


def missing_resources(build_dir: Path) -> List[str]:
    return [rel for rel in native_resources() if not (build_dir / rel).is_file()]


def license_files() -> List[str]:
    """LICENSE_FILES of build_GUI_portable.py: what both builds put next to the exe."""
    return list(_load_module(ROOT / "build_GUI_portable.py", "_release_build_gui_license").LICENSE_FILES)


def license_problems(build_dir: Path) -> List[str]:
    """What the GPL needs next to the exe and is missing."""
    problems = [name for name in license_files() if not (build_dir / name).is_file()]
    third_party = build_dir / "THIRD-PARTY.txt"
    if third_party.is_file() and "{source_url}" in third_party.read_text(encoding="utf-8"):
        problems.append("the source link in THIRD-PARTY.txt (set SOURCE_URL in UStudio/app_info.py, then rebuild)")
    return problems


def _load_build_script_lists():
    """GUI_DOCS and CLI_DOCS from the build scripts (so the file lists are defined in one place)."""
    sys.path.insert(0, str(ROOT))
    gui = _load_module(ROOT / "build_GUI_portable.py", "_release_build_gui")
    cli = _load_module(ROOT / "build_CLI_portable (one file).py", "_release_build_cli")
    return list(gui.GUI_DOCS), list(cli.CLI_DOCS)


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_cli_zip(src_dir: Path, out_zip: Path, files: Iterable[str]) -> Dict[str, Path]:
    """Flat zip of the named files; returns {name in zip: source path}."""
    entries = {}
    for name in files:
        if not (src_dir / name).is_file():
            raise ReleaseError(f"{src_dir / name} is missing — run the CLI build first")
        entries[name] = src_dir / name
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, path in entries.items():
            z.write(path, name)
    return entries


def build_gui_zip(src_dir: Path, out_zip: Path, root_name: str):
    """Zip of the whole standalone build under one root folder; returns ({name in zip: source}, skipped junk)."""
    entries: Dict[str, Path] = {}
    skipped: List[str] = []
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(src_dir.rglob("*")):
            rel = path.relative_to(src_dir).as_posix()
            if is_junk(rel):
                if path.is_file():
                    skipped.append(rel)
                continue
            if path.is_dir():
                if not any(path.iterdir()):
                    z.writestr(f"{root_name}/{rel}/", "")
                continue
            z.write(path, f"{root_name}/{rel}")
            entries[f"{root_name}/{rel}"] = path
    return entries, skipped


def verify_zip(zip_path: Path, entries: Dict[str, Path]) -> None:
    with zipfile.ZipFile(zip_path) as z:
        bad = z.testzip()
        if bad is not None:
            raise ReleaseError(f"{zip_path.name}: corrupt entry {bad}")
        names = set(z.namelist())
        for name, src in entries.items():
            if name not in names:
                raise ReleaseError(f"{zip_path.name}: {name} is missing from the zip")
            if hashlib.sha256(z.read(name)).digest() != bytes.fromhex(sha256(src)):
                raise ReleaseError(f"{zip_path.name}: {name} differs from the build")


def _check_build(exe: Path, version: str, label: str) -> None:
    if not exe.is_file():
        raise ReleaseError(f"{exe} not found — build the {label} first")
    found = exe_file_version(exe)
    expected = f"{version}.0"
    if found != expected:
        raise ReleaseError(f"{exe.name} has version {found}, expected {expected} — it is a stale build; rebuild the {label}")
    newer = sources_newer_than(exe, skip_qt=(label == "CLI"))
    if newer:
        print(f"  WARNING: sources changed after the {label} was built: {', '.join(newer)}"
              f"{' ...' if len(newer) == 5 else ''}")


def _target_path(out_dir: Path, name: str, overwrite: bool) -> Path:
    target = out_dir / name
    if target.exists() and not overwrite:
        raise ReleaseError(f"{target} already exists (use --overwrite to replace it)")
    return target


def _finish(tmp: Path, target: Path) -> None:
    if target.exists():
        target.unlink()
    tmp.replace(target)


def make_cli(out_dir: Path, version: str, overwrite: bool, cli_docs: List[str]) -> Path:
    print("CLI:")
    _check_build(CLI_BUILD / "ustudio_cli.exe", version, "CLI")
    missing = license_problems(CLI_BUILD)
    if missing:
        raise ReleaseError("the CLI build lacks: " + ", ".join(missing))
    target = _target_path(out_dir, f"UStudio CLI v{version}.zip", overwrite)
    tmp = target.with_suffix(".zip.part")
    try:
        entries = build_cli_zip(CLI_BUILD, tmp, ["ustudio_cli.exe"] + cli_docs + license_files())
        verify_zip(tmp, entries)
        _finish(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    print(f"  {target.name}: {target.stat().st_size / 2**20:.1f} MB, {len(entries)} files "
          f"(the CLI payload itself is not inspected)")
    return target


def make_gui(out_dir: Path, version: str, overwrite: bool, gui_docs: List[str]) -> Path:
    print("GUI:")
    _check_build(GUI_BUILD / "UStudio.exe", version, "GUI")
    missing = missing_resources(GUI_BUILD) + [f"docs/ru/{n}" for n in gui_docs if not (GUI_BUILD / "docs" / "ru" / n).is_file()]
    missing += license_problems(GUI_BUILD)
    if missing:
        raise ReleaseError("the GUI build lacks files that must ship: " + ", ".join(missing))
    target = _target_path(out_dir, f"UStudio GUI v{version}.zip", overwrite)
    tmp = target.with_suffix(".zip.part")
    try:
        entries, skipped = build_gui_zip(GUI_BUILD, tmp, f"UStudio v{version}")
        verify_zip(tmp, entries)
        _finish(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    if skipped:
        print(f"  left out (repository/editor leftovers): {', '.join(skipped)}")
    print(f"  {target.name}: {target.stat().st_size / 2**20:.1f} MB, {len(entries)} files")
    return target


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Zip the portable GUI/CLI builds into a release folder.")
    ap.add_argument("--out", type=Path, default=DEFAULT_RELEASES, help=f"releases folder (default: {DEFAULT_RELEASES})")
    ap.add_argument("--only", choices=("gui", "cli"), help="prepare just one of the two")
    ap.add_argument("--overwrite", action="store_true", help="replace zips that already exist")
    args = ap.parse_args(argv)

    try:
        version = read_version()
        gui_docs, cli_docs = _load_build_script_lists()
        out_dir = args.out / f"v{version}"
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"Release v{version} -> {out_dir}")
        made = []
        failed = False
        for name, fn, docs in (("gui", make_gui, gui_docs), ("cli", make_cli, cli_docs)):
            if args.only and args.only != name:
                continue
            try:
                made.append(fn(out_dir, version, args.overwrite, docs))
            except ReleaseError as e:
                failed = True
                print(f"  ERROR: {e}")
        print()
        for path in made:
            print(f"{sha256(path)}  {path.name}")
        if failed:
            print("\nSome zips were NOT made (see the errors above).")
            return 1
        log = out_dir / f"Лог обновления UStudio v{version}.txt"
        print("\nDone." + ("" if log.is_file() else f" NOTE: no update log yet ({log.name})."))
        return 0
    except ReleaseError as e:
        print(f"ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
