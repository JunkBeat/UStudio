"""Builds UStudio into a portable, folder-of-files distribution using Nuitka's
--standalone mode (NOT --onefile — a self-extracting single exe is exactly what
PyInstaller already gives you, and it's what makes AV/SmartScreen twitchy in the
first place; --standalone instead produces an ordinary folder containing a real
native launcher exe plus its DLLs, which behaves and looks like normal compiled
software).

Usage:
    python build_GUI_portable.py

What it does:
    1. Makes sure Nuitka is installed (installs it into the current interpreter's
       environment if missing — run this from the same venv/interpreter you use to
       run the app).
    2. Compiles main.py with the PyQt6 plugin enabled (bundles the Qt platform/
       style/imageformat plugins UStudio needs to actually start, plus the
       "multimedia" plugin category explicitly — see the --include-qt-plugins
       comment below for why Nuitka's own default set silently misses it under
       Qt6) and explicitly includes TypeTreeGeneratorAPI's bundled native DLLs
       (capstone.dll, TypeTreeGeneratorAPI.dll) — those are loaded at runtime
       (not via a Python import Nuitka's static analysis can see), so they'd
       otherwise be silently left out.
    3. Explicitly re-copies UnityPy/resources/, archspec/, and
       TypeTreeGeneratorAPI/ into the built dist folder after Nuitka finishes
       (see copy_extra_resources()) — a deterministic safety net independent of
       Nuitka's own inclusion heuristics for these three specifically-known-
       fragile cases, rather than re-diagnosing this class of gap after every
       future Nuitka version bump.
    4. Leaves the result in dist/UStudio/ as a plain folder — copy it wherever,
       run UStudio.exe inside it, nothing to install or extract.

Nuitka needs a C compiler the first time it runs; if none is found (MSVC via
Visual Studio Build Tools, or MinGW64) it offers to download a private MinGW64
copy just for itself — --assume-yes-for-downloads below auto-confirms that
instead of the build hanging on an interactive prompt.
"""

import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent / "UStudio"
ENTRY_POINT = PROJECT_DIR / "main.py"
DIST_DIR = Path("dist")
APP_NAME = "UStudio"
# Windows PE version resources are all-or-nothing: setting --product-name/
# --file-description without also setting --product-version/--file-version is a
# hard Nuitka error ("these can not have good defaults, but are forced to be
# present by the OS"). Windows PE version resources require this 4-part form
# specifically — kept in sync BY HAND with config.py's own APP_VERSION (the
# 3-part semver shown in the title bar), not imported from there: this script
# deliberately has no dependency on the app's own code at all (see the plain
# stdlib-only imports above), so it doesn't need PyQt6/UnityPy installed just
# to run a build.
APP_VERSION = "1.5.0.0"
# Shows up as the "Company" field in Explorer's file Properties > Details tab
# for UStudio.exe — the standard Windows place for this, independent of
# --product-name/--file-description above (no version-pairing requirement of
# its own).
AUTHOR = "Ambigram"


def generate_app_icon(ico_path: Path) -> None:
    """Renders app_icon.py's procedural logo into a real multi-resolution
    .ico file, since Nuitka's --windows-icon-from-ico (used below) needs an
    actual file path to embed as the compiled UStudio.exe's OWN icon — the
    one Explorer/the taskbar show before the app ever launches. That's a
    separate thing from main.py's app.setWindowIcon(app_icon.get_app_icon()),
    which only sets the in-app title-bar/taskbar icon once the app is
    already running; without this, the built exe fell back to Nuitka's own
    generic default icon (the "doesn't seem to contain the program's logo"
    report).

    This project deliberately ships no image/icon asset files at all (see
    app_icon.py's own docstring — every icon anywhere in this app is drawn
    procedurally with QPainterPath, not loaded from a file) — this .ico is a
    build-time ARTIFACT generated fresh by this script each run, not a
    checked-in binary, so that convention still holds for anything actually
    committed to the repo."""
    sys.path.insert(0, str(PROJECT_DIR))
    from io import BytesIO

    from PIL import Image
    from PyQt6.QtCore import QBuffer, QIODevice
    from PyQt6.QtWidgets import QApplication

    # The QApplication's return value MUST be kept alive in a real variable —
    # `QApplication.instance() or QApplication([])` as a bare expression
    # statement (no assignment) was a real, reproducible bug here: with
    # nothing holding a Python reference to the newly-constructed instance,
    # it's garbage-collected immediately, PyQt6/sip destroys the underlying
    # C++ QApplication right along with it, and the very next Qt GUI call
    # (QPixmap(size, size) inside render_logo_pixmap) segfaults the
    # interpreter outright — a silent native crash with no Python traceback
    # at all, confirmed by bisecting with flushed debug prints planted line
    # by line until the exact crashing statement was found.
    _app = QApplication.instance() or QApplication([])  # noqa: F841 — kept alive deliberately, see above
    import UStudio.app_icon as app_icon

    pil_images = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = app_icon.render_logo_pixmap(size, "color")
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.ReadWrite)
        pixmap.save(buf, "PNG")
        pil_images.append(Image.open(BytesIO(bytes(buf.data()))).convert("RGBA"))

    ico_path.parent.mkdir(parents=True, exist_ok=True)
    # Real bug found by inspecting the actual on-disk .ico bytes, not by
    # trusting "it didn't raise": Pillow's ICO writer only embeds sizes at or
    # below the BASE image's own resolution — saving from pil_images[0] (16x16,
    # the smallest) silently produced a 16x16-ONLY .ico (299 bytes) despite
    # passing every size in `sizes` and the rest via `append_images`, no error
    # or warning either. The base must be the LARGEST image, with every
    # smaller one in append_images — verified this produces all 7 real,
    # independently-rendered sizes (16 through 256), not just a single one
    # cropped/resized from it, by parsing the .ico directory's own entry
    # count and per-entry byte sizes directly.
    pil_images[-1].save(
        ico_path,
        format="ICO",
        sizes=[(im.width, im.height) for im in pil_images],
        append_images=pil_images[:-1],
    )


# 4.2 is the first release with official Python 3.14 support and the "C
# compilation scalability" work (reduced generated-C volume) that fixes the
# MSVC C1002 "out of memory in pass 2" crash this project hit on its own
# largest generated files (UnityPy.classes.generated.c, preview_panel.c) under
# the previously-installed 4.1.3. Anything older than this is known-broken for
# this project's build, not just untested.
MIN_NUITKA_VERSION = (4, 2, 1)


def _parse_version(v: str) -> tuple[int, ...]:
    parts = []
    for chunk in v.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def ensure_nuitka_installed() -> None:
    from importlib.metadata import PackageNotFoundError, version

    try:
        installed = version("nuitka")
    except PackageNotFoundError:
        print("Nuitka isn't installed in this interpreter — installing it now...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "nuitka"],
            check=True,
        )
        return

    if _parse_version(installed) < MIN_NUITKA_VERSION:
        print(
            f"Installed Nuitka {installed} is older than "
            f"{'.'.join(map(str, MIN_NUITKA_VERSION))} — upgrading (needed for its "
            "C-compilation-scalability fixes and official Python 3.14 support)..."
        )
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "nuitka"],
            check=True,
        )


def ensure_requirements_installed() -> None:
    """Ensures all dependencies from requirements.txt are installed
    before running the build process."""
    # requirements.txt is assumed to be in the project root (one level up from UStudio/)
    req_path = Path(__file__).resolve().parent.parent / "requirements.txt"
    if not req_path.is_file():
        # Fallback to current directory if not found in parent
        req_path = Path(__file__).resolve().parent / "requirements.txt"

    if req_path.is_file():
        print(f"Installing dependencies from {req_path.name}...")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-r",
                str(req_path),
                "--prefer-binary",
            ],
            check=True,
        )
    else:
        print("requirements.txt not found, skipping dependency installation.")


def remove_tree(path: Path) -> None:
    """shutil.rmtree that also deletes read-only files. On Windows a plain rmtree stops with
    PermissionError on read-only files such as git objects (".git/objects/..") — that is how a
    leftover dist-cli/ from an old build once made the CLI build fail before compiling anything."""
    def _on_error(func, failed_path, _exc):
        os.chmod(failed_path, stat.S_IWRITE)
        func(failed_path)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_on_error)
    else:
        shutil.rmtree(path, onerror=_on_error)


def strip_vcs_folders(final_dir: Path) -> None:
    """Removes ".git" folders from the finished build. Nuitka's --include-package-data=UnityPy treats
    the vendored UnityPy's own git repository as package data, so a release used to contain
    UnityPy/.git (44 MB of history) — never wanted in a distribution."""
    for git_dir in sorted(final_dir.rglob(".git")):
        if git_dir.is_dir():
            remove_tree(git_dir)
            print(f"Removed {git_dir}")


DOCS_DIR = Path(__file__).resolve().parent / "docs"
GUI_DOCS = ["sdf_map.md"]    # rendered by the SDF help window (UStudio/help_docs.py finds docs/<lang> next to the exe)
GUI_DOC_LANGUAGES = ["ru", "en", "uk"]    # the help window shows the one of the interface language


# Qt's own translation files (message box buttons, text field menus, file dialogs) for the languages of
# Настройки -> Язык; Nuitka does not carry them. app_language.py looks for them in locales/qt.
QT_TRANSLATION_FILES = ["qtbase_ru.qm", "qtbase_uk.qm", "qtmultimedia_ru.qm", "qtmultimedia_uk.qm"]


def copy_locales(dest_dir: Path) -> None:
    """UStudio's catalogs (UStudio/locales/*.json, core/i18n.py) and Qt's translation files into dest_dir.
    A missing file stops the build: without it the program would silently show another language."""
    src_dir = PROJECT_DIR / "locales"
    catalogs = sorted(src_dir.glob("*.json"))
    if not catalogs:
        raise SystemExit(f"copy_locales: no catalogs in {src_dir}")
    if dest_dir.exists():
        remove_tree(dest_dir)
    (dest_dir / "qt").mkdir(parents=True)
    for src in catalogs:
        shutil.copy2(src, dest_dir / src.name)
    from PyQt6.QtCore import QLibraryInfo
    qt_dir = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    for name in QT_TRANSLATION_FILES:
        if not (qt_dir / name).is_file():
            raise SystemExit(f"copy_locales: Qt translation not found: {qt_dir / name}")
        shutil.copy2(qt_dir / name, dest_dir / "qt" / name)
    print(f"Copied {len(catalogs)} catalogs + {len(QT_TRANSLATION_FILES)} Qt translations -> {dest_dir}")


import shutil
from pathlib import Path

def copy_docs(dest_dir: Path, names: list[str], src_dir: Path = DOCS_DIR) -> None:
    """Copies the specified files or directories from src_dir into dest_dir/docs. A missing path
    stops the build: the GUI help window and the CLI README both point at these files, so a
    build without them would silently lose documentation."""
    docs_dest_dir = dest_dir / "docs"
    docs_dest_dir.mkdir(parents=True, exist_ok=True)
    
    for name in names:
        src = src_dir / name
        target = docs_dest_dir / name

        if src.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(src, target)
            print(f"Copied directory {src} -> {target}")
        elif src.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            print(f"Copied {src} -> {target}")
        else:
            raise SystemExit(f"expected documentation file or directory not found: {src}")


LICENSE_FILES = ["LICENSE.txt", "THIRD-PARTY.txt"]    # next to the exe in both builds (GPL: the licence travels with the program)


def read_source_url() -> str:
    """app_info.SOURCE_URL, read as text (this script does not import the app)."""
    text = (PROJECT_DIR / "app_info.py").read_text(encoding="utf-8")
    m = re.search(r'^SOURCE_URL\s*=\s*"([^"]*)"', text, flags=re.M)
    return m.group(1) if m else ""


def copy_license_files(dest_dir: Path) -> None:
    """LICENSE (as LICENSE.txt, so Windows opens it) and THIRD-PARTY.txt with the source link filled in.
    An empty SOURCE_URL only warns here (a test build); prepare_release.py refuses to zip such a build."""
    root = PROJECT_DIR.parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / "LICENSE", dest_dir / "LICENSE.txt")
    url = read_source_url()
    if not url:
        print("WARNING: SOURCE_URL in UStudio/app_info.py is empty; THIRD-PARTY.txt names no source link")
    text = (root / "THIRD-PARTY.txt").read_text(encoding="utf-8")
    (dest_dir / "THIRD-PARTY.txt").write_text(text.replace("{source_url}", url or "{source_url}"), encoding="utf-8")
    print(f"Copied LICENSE.txt, THIRD-PARTY.txt -> {dest_dir}")


def copy_extra_resources(final_dir: Path) -> None:
    """Explicit, deterministic copy of three specific folders into the built
    dist tree, instead of trusting Nuitka's own --include-package-data/
    dependency-following to keep catching them on every future build.

    Confirmed this session (see UnityPy/helpers/Fsb5Encoder.py's own comment)
    that Nuitka's inclusion of a resource-only subpackage (data files, no
    Python code anywhere doing a real, statically-traceable `import` of it)
    is NOT reliable — UnityPy.resources.fsb5_converter's DLLs were being
    copied to disk correctly by --include-package-data=UnityPy, but the
    *package itself* wasn't always registered as importable, and that class
    of gap is inherently sensitive to how the code happens to reference the
    resource (a dynamic importlib.resources.files(name) vs an actual `import`
    statement) — not something to keep re-diagnosing after every Nuitka
    version bump. archspec and TypeTreeGeneratorAPI already happened to come
    through correctly in the last build via Nuitka's own default dependency
    tracing (verified by inspecting dist/UStudio/archspec and .../
    TypeTreeGeneratorAPI directly), but that's Nuitka's own heuristic, not a
    guarantee — copying them explicitly here makes the build's correctness
    independent of it, for these three specifically-known-fragile cases.

    site-packages is located via sys.executable rather than hardcoded, so
    this works on whichever machine/interpreter actually runs the build."""
    site_packages = Path(sys.executable).resolve().parent / "Lib" / "site-packages"

    copies = [
        (PROJECT_DIR / "UnityPy" / "resources", final_dir / "UnityPy" / "resources"),
        # UStudio's own bundled tools (the Il2CppDumper fork for «Подготовить скрипты IL2CPP»): data files only,
        # no Python imports them, so Nuitka would not carry them. GUI only — the CLI build leaves them out.
        (PROJECT_DIR / "bundled_tools", final_dir / "bundled_tools"),
        (site_packages / "archspec", final_dir / "archspec"),
        (site_packages / "TypeTreeGeneratorAPI", final_dir / "TypeTreeGeneratorAPI"),
    ]
    for src, dst in copies:
        if not src.is_dir():
            raise SystemExit(f"copy_extra_resources: expected folder not found: {src}")
        if dst.exists():
            remove_tree(dst)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", ".git"))
        print(f"Copied {src} -> {dst}")


def build() -> Path:
    if not ENTRY_POINT.exists():
        raise SystemExit(f"Entry point not found: {ENTRY_POINT}")

    ensure_requirements_installed()
    ensure_nuitka_installed()

    if DIST_DIR.exists():
        print(f"Removing previous build output: {DIST_DIR}")
        remove_tree(DIST_DIR)

    icon_path = DIST_DIR / "app_icon.ico"
    print(f"Generating app icon: {icon_path}")
    generate_app_icon(icon_path)

    cmd = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        # Not --onefile: a folder of files, not a self-extracting single exe —
        # see the module docstring for why.
        "--enable-plugin=pyqt6",
        # TypeTreeGeneratorAPI's capstone.dll/TypeTreeGeneratorAPI.dll are loaded at
        # runtime (ctypes-style), not via a Python import — Nuitka's static import
        # analysis can't see that, so they must be pulled in explicitly or the built
        # app will fail (or silently misbehave) the moment IL2CPP TypeTree generation
        # is actually attempted.
        "--include-package-data=TypeTreeGeneratorAPI",
        # UnityPy.helpers.Tpk reads UnityPy/resources/lzma.tpk (a data file, not a Python
        # import) at module-init time — Nuitka's import-following doesn't see it, so without
        # this the standalone build is missing it entirely and crashes on startup with
        # FileNotFoundError before the Qt window ever appears (confirmed via a --windows-
        # console-mode=disable build: the traceback is real, it's just silently redirected
        # to the null device instead of showing anywhere, and it's a clean Python exception
        # so Windows Event Log never sees it either).
        "--include-package-data=UnityPy",
        # The vendored UnityPy is its own git repository: without this the .git folder (44 MB of history,
        # full of read-only files that also break Nuitka's own output cleanup) ships as "package data".
        "--noinclude-data-files=UnityPy/.git/*",
        # Other repository/editor leftovers that --include-package-data=UnityPy sweeps in (found in the 1.2.0 build).
        "--noinclude-data-files=UnityPy/.vscode/*",
        "--noinclude-data-files=UnityPy/.gitattributes",
        "--noinclude-data-files=UnityPy/classes/generated.py.backup",
        # Real reported bug: AudioPreviewWidget's QMediaPlayer loads a clip fine in
        # the built exe but shows "0:00 / 0:00" and never reports a real duration —
        # works correctly in normal (non-frozen) Python. Root cause, confirmed
        # against Nuitka's own plugin source (nuitka/plugins/standard/
        # PySidePyQtPlugin.py) rather than guessed: Nuitka's "sensible" default Qt-
        # plugin set (its own auto-included category list when no --include-qt-
        # plugins is given) lists "mediaservice" — Qt5's name for this plugin
        # category. PyQt6/Qt6 renamed it to "multimedia" (confirmed directly: this
        # machine's real PyQt6\Qt6\plugins\ folder has "multimedia", no
        # "mediaservice" at all), so the name never matches and the category is
        # silently skipped — confirmed via the actual prior build log line
        # ("Including Qt plugins 'iconengines,imageformats,platforms,styles,tls'",
        # no multimedia) and the dist folder itself lacking
        # PyQt6/Qt6/plugins/multimedia entirely. Without it, QMediaPlayer has no
        # backend (windowsmediaplugin.dll/ffmpegmediaplugin.dll) to actually decode
        # media or report duration/position — this is a naming mismatch in
        # Nuitka's own default list for Qt6, not something specific to this
        # project's audio code.
        "--include-qt-plugins=multimedia",
        "--windows-console-mode=disable",
        f"--windows-icon-from-ico={icon_path.resolve()}",
        "--assume-yes-for-downloads",
        # The build was crashing with MSVC-internal errors (C1002 "out of memory in
        # pass 2", C1356 "can't find mspdbcore.dll") on several huge generated files
        # (UnityPy.classes.generated.c — ~700 classes in one module, numpy.ma.core.c,
        # preview_panel.c) under Nuitka 4.1.3. Root cause confirmed to be Nuitka's own
        # generated-C volume on Python 3.14 for these large modules, not a project bug
        # or (as first suspected) parallel cl.exe/mspdbsrv contention — the real fix
        # was the MIN_NUITKA_VERSION bump above (4.2's "C compilation scalability"
        # work). --mingw64 was tried as a workaround but is rejected outright by
        # Nuitka on Python 3.13+, and is unnecessary now anyway. --low-memory/--jobs=2
        # are kept as a cheap additional safety margin against memory pressure, not
        # the primary fix.
        "--low-memory",
        "--jobs=2",
        # Absolute path: the subprocess below runs with cwd=PROJECT_DIR (UStudio/), so a
        # relative "dist" here would land at UStudio/dist instead of this script's own
        # dist/ — silently breaking the built_dir/final_dir rename below, which resolves
        # DIST_DIR relative to *this* process's cwd.
        f"--output-dir={DIST_DIR.resolve()}",
        f"--output-filename={APP_NAME}.exe",
        f"--product-name={APP_NAME}",
        f"--file-description={APP_NAME}",
        f"--company-name={AUTHOR}",
        f"--product-version={APP_VERSION}",
        f"--file-version={APP_VERSION}",
        str(ENTRY_POINT),
    ]

    print("Running:", " ".join(cmd))
    subprocess.run(cmd, cwd=PROJECT_DIR, check=True)

    # --standalone names the produced folder after the entry script: main.dist/
    built_dir = DIST_DIR / f"{ENTRY_POINT.stem}.dist"
    final_dir = DIST_DIR / APP_NAME
    if built_dir.exists():
        built_dir.rename(final_dir)

    copy_extra_resources(final_dir)
    strip_vcs_folders(final_dir)
    
    source_docs = Path(__file__).resolve().parent / "docs"
    target_docs = final_dir / "docs"
    if source_docs.is_dir():
        if target_docs.exists():
            remove_tree(target_docs)
        shutil.copytree(source_docs, target_docs, ignore=shutil.ignore_patterns("__pycache__", ".git"))
        print(f"docs was copied -> {target_docs}")

    copy_locales(final_dir / "locales")
    copy_license_files(final_dir)

    return final_dir


if __name__ == "__main__":
    out_dir = build()
    print()
    print(f"Done. Portable build: {out_dir}")
    print(f"Run: {out_dir / (APP_NAME + '.exe')}")
