"""Builds UStudio's console-mode CLI (ustudio_cli.py) into a single portable
.exe via Nuitka's --onefile mode — deliberately a SEPARATE build from
build_GUI_portable.py's --standalone GUI build, for two reasons:

  1. The CLI entry point is explicitly designed to stay importable/runnable
     without PyQt6 at all (see ustudio_cli.py's own module docstring, and
     core/__init__.py's "nothing under this package may import PyQt6" rule)
     — bundling Qt6's DLLs/plugins into a CLI-only build would be pure dead
     weight (tens of MB of Qt binaries a console tool never touches) and
     defeats the whole point of having a Qt-free core/ layer.
  2. --onefile suits a CLI tool much better than --standalone: a single
     ustudio_cli.exe is something you can drop on PATH or next to a game's
     own folder and just run, whereas a whole folder-of-files distribution
     (the right choice for the GUI — see build_GUI_portable.py's own
     docstring on why NOT --onefile there) is awkward for a tool meant to be
     invoked directly from scripts/terminals.

Output goes to dist-cli/ — a separate folder from build_GUI_portable.py's own
dist/, specifically so running either script never collides with or gets
mixed up with the other's output.

Usage:
    python "build_CLI_portable (one file).py"

What it does:
    1. Makes sure Nuitka is installed (same MIN_NUITKA_VERSION requirement as
       build_GUI_portable.py — this build compiles the same huge
       UnityPy.classes.generated.py file, since core/loader.py imports
       UnityPy the same way main.py does; the MSVC C1002/C1356 crash that
       version bump fixes is not a GUI-specific issue).
    2. Compiles ustudio_cli.py with --onefile, explicitly EXCLUDING PyQt6
       (--nofollow-import-to=PyQt6 — a defensive, fail-fast belt-and-
       suspenders check: the CLI's own import graph should never reach
       PyQt6 to begin with, per core/'s own architecture rule, so this
       should normally be a no-op; if a future change ever DOES introduce
       such a path, this turns it into a loud build-time/runtime failure
       instead of silently shipping a Qt-bloated "CLI" exe). No
       --enable-plugin=pyqt6, no --include-qt-plugins either — this is a
       console tool, it never touches Qt at runtime. The exe DOES get a real
       icon (--windows-icon-from-ico), via build_GUI_portable.py's own
       generate_app_icon() reused as-is (imported, not copy-pasted, so the
       two builds' icons can't drift apart) — that function needs a real
       QApplication/PyQt6 instance to render app_icon.py's procedural logo,
       but that happens in THIS SCRIPT's own process at build time only; it
       has no bearing on what Nuitka actually compiles into ustudio_cli.exe,
       which is driven entirely by ustudio_cli.py's own import graph (still
       PyQt6-free, still checked by --nofollow-import-to above). A build
       tool using PyQt6 to render a PNG is not the same thing as the built
       CLI depending on PyQt6.
    3. Bundles the actual DATA files this build needs through TWO different
       mechanisms, because a first attempt at fixing a real, confirmed crash
       showed these are NOT interchangeable:

       --include-data-dir=UnityPy/resources=UnityPy/resources and
       --include-data-dir=<site-packages>/archspec=archspec cover ordinary
       (non-binary) files: UnityPy/resources/lzma.tpk (read at module-init
       time, not import-traceable — see build_GUI_portable.py's own
       copy_extra_resources() comment) and archspec's own .json/.py data.
       This mechanism is correctly NOT trusted for TypeTreeGeneratorAPI/
       (its own DLLs) — see below for why.

       cli_onefile_dlls.nuitka-package.config.yml (a Nuitka "package
       configuration" file, passed via
       --user-package-configuration-file) covers every genuinely native
       .dll/.exe this build depends on: TypeTreeGeneratorAPI's own
       TypeTreeGeneratorAPI.dll/capstone.dll (ctypes-loaded IL2CPP TypeTree
       generation), plus UnityPy/resources/bcn_encoder/'s DLLs (pythonnet-
       loaded texture encoding) and UnityPy/resources/fsb5_converter/'s
       DLLs+exe (subprocess-launched audio encoding). **This split is not
       optional or a style choice** — confirmed directly against Nuitka's
       own documentation and its own shipped standard.nuitka-package-
       config.yml examples (cryptoauthlib/clr_loader.ffi): both
       --include-data-dir AND --include-package-data explicitly, always,
       unconditionally exclude every .dll/.exe file, regardless of which
       folder they're pointed at ("DLLs and extension modules are not data
       files and never included like this"). An EARLIER version of this
       build tried --include-data-dir=...=TypeTreeGeneratorAPI (and
       --include-package-data=TypeTreeGeneratorAPI alongside it) and still
       crashed on a real IL2CPP fixture with "Could not find module
       '.../TypeTreeGeneratorAPI/TypeTreeGeneratorAPI.dll' (or one of its
       dependencies)" — a first (WRONG) theory blamed Windows' DLL search
       path, but a direct local reproduction (loading the real DLL from an
       equivalent folder layout via plain ctypes, no Nuitka involved at all)
       loaded it FINE, disproving that theory outright and pointing at
       Nuitka's own bundling step instead — confirmed moments later by its
       own documented behavior above. bcn_encoder/fsb5_converter were never
       actually tested before this fix (the reported crash only ever
       exercised the IL2CPP path) but were found to have the exact same gap
       by directly grepping this project's own UnityPy/resources/ tree for
       every .dll/.exe file rather than assuming the bug was scoped to only
       the one already-reported case.
    4. Leaves the result as dist-cli/ustudio_cli.exe — a single file,
       nothing to install or extract. --remove-output cleans up Nuitka's own
       intermediate *.build/*.onefile-build cache folders afterward so
       dist-cli/ ends up holding just that one deliverable.

Nuitka needs a C compiler the first time it runs; if none is found (MSVC via
Visual Studio Build Tools, or MinGW64) it offers to download a private MinGW64
copy just for itself — --assume-yes-for-downloads below auto-confirms that
instead of the build hanging on an interactive prompt.

*** REAL BUG, CONFIRMED AND FIXED — READ THIS BEFORE ADDING A NEW ENTRY TO
cli_onefile_dlls.nuitka-package.config.yml ***

Found testing the actual built 1.1.0 exe, not just the plain Python script:
--video-transcode failed outright with "ffmpeg/ffprobe not found", even
though the YAML file already had a correctly-written UnityPy.resources.ffmpeg
entry (right module name, right prefixes, right `executable: 'yes'` — nothing
wrong with the entry itself). Root-caused via an isolated, minimal --onefile
reproduction (a throwaway package with the identical shape: a resource-only
submodule, empty __init__.py, referenced ONLY by a YAML module-name entry,
never a real Python `import` anywhere) — confirmed directly, not guessed:

    Nuitka's package-config DLL-bundling plugin (the one --user-package-
    configuration-file drives) only processes a module-name entry for a
    module Nuitka has ALREADY decided is part of the compiled program's own
    import graph. A module that exists ONLY as a YAML config target, with no
    corresponding `import` anywhere in the actual source, is never
    "discovered" — so its dll config entry silently never fires, no matter
    how correctly it's written, no error, no warning. The repro's DLL/EXE
    files were absent from the onefile dist folder until an explicit
    `import <that submodule>` was added to the repro's own main script, at
    which point they appeared correctly on the very next build.

This bit THREE of the four entries in cli_onefile_dlls.nuitka-package.config.yml
at once, not just ffmpeg — UnityPy.resources.ffmpeg, UnityPy.resources.
fsb5_converter, and UnityPy.resources.bcn_encoder are ALL resolved via pure
filesystem-path math relative to __file__ (deliberately, to sidestep a
DIFFERENT, earlier Nuitka bug — see Fsb5Encoder.py's/BcnEncoder.py's own
_RESOURCE_DIR comments), so none of them were ever the target of a real
Python `import` statement anywhere in this codebase. Audio (FSB5) and BC7
texture encoding were very likely ALSO silently broken in every --onefile CLI
build before this fix, not just video transcode — they just hadn't been
tested. TypeTreeGeneratorAPI, the fourth entry, was unaffected: it's a real
third-party package with a genuine top-level `import TypeTreeGeneratorAPI`
in UnityPy/helpers/TypeTreeGenerator.py, so Nuitka already discovers it
naturally.

**Fix applied**: a minimal, no-op `import UnityPy.resources.<name>  # noqa:
F401` added directly in core/video_transcode.py, UnityPy/helpers/
Fsb5Encoder.py, and UnityPy/helpers/BcnEncoder.py — right next to each
module's own _RESOURCE_DIR/FFMPEG_EXE-style path-resolution code, so the
requirement stays visible exactly where a future edit to that resolution
logic would be made. Nothing in any of those three files actually USES the
imported name; its only job is to make Nuitka's static analysis trace the
submodule so the matching YAML dll entry actually fires. Verified two ways
before trusting it: Nuitka's own build log now says "Found N files DLLs from
UnityPy.resources.<name> installation" for all three (it said nothing at all
for them before this fix — compare against a build log from before this
change if you ever want to see the negative case), and a real transcode
round-trip through the rebuilt exe produced genuine WebM output with correct
metadata.

**Confirmed NOT a GUI problem**: build_GUI_portable.py's --standalone build
uses --include-package-data=UnityPy instead of this YAML dll-config
mechanism entirely — a completely different Nuitka code path that never
requires this "must be actually imported" condition. Checked the real,
already-built dist/ folder directly: ffmpeg.exe/ffprobe.exe and every
fsb5_converter/bcn_encoder DLL were already present there, before and
independent of this CLI-side fix.

**If you add a new entry to cli_onefile_dlls.nuitka-package.config.yml
later** (a new vendored resource folder, a new native dependency): that YAML
entry alone is NOT enough for a --onefile build. You must ALSO add a real
`import <the module the entry names>` statement somewhere Nuitka's own
analysis will actually reach (anywhere in the normal import graph — it does
not need to be used, just imported) — otherwise the new dependency will
silently vanish from the built exe exactly like these three did, with no
error at build time OR at runtime until someone actually exercises that
feature and hits a "file not found"-style failure. This is a Nuitka
mechanism, not a bug in this project's own build script — the same
requirement will apply to any onefile build using this YAML config
technique, indefinitely, unless a future Nuitka version changes it.
"""

import subprocess
import sys
from pathlib import Path

# Reused, not duplicated, so the CLI and GUI builds can never end up with two
# different icons by accident — see the module docstring, point 2, for why
# importing this (a build-time-only PyQt6 use, in THIS process) doesn't
# reintroduce any PyQt6 dependency into the compiled ustudio_cli.exe itself.
from build_GUI_portable import copy_docs, copy_license_files, generate_app_icon, remove_tree, strip_vcs_folders

PROJECT_DIR = Path(__file__).resolve().parent / "UStudio"
ENTRY_POINT = PROJECT_DIR / "ustudio_cli.py"
DIST_DIR = Path("dist-cli")
CLI_DOCS = [
    "en/ustudio_cli_readme_english.txt",
    "ru/ustudio_cli_readme_russian.txt",
    "uk/ustudio_cli_readme_ukrainian.txt",
]   # from docs/, copied next to ustudio_cli.exe
APP_NAME = "ustudio_cli"
DISPLAY_NAME = "UStudio CLI"
# Same all-or-nothing Windows PE version-resource rule build_GUI_portable.py
# already documents (setting product-name/file-description without also
# setting product-version/file-version is a hard Nuitka error) — kept in
# sync with that build's own version rather than tracked separately, since
# both ship from the same source tree.
APP_VERSION = "1.5.0.0"
AUTHOR = "Ambigram"

# Same reasoning as build_GUI_portable.py's own MIN_NUITKA_VERSION: the
# MSVC C1002/C1356 crash it fixes is about Nuitka's generated-C volume for
# UnityPy.classes.generated.py, which this build compiles too (core/loader.py
# imports UnityPy the same way main.py does) — not a GUI-specific issue.
MIN_NUITKA_VERSION = (4, 3, 1)


def _parse_version(v: str) -> "tuple[int, ...]":
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
        installed = None

    if installed is None or _parse_version(installed) < MIN_NUITKA_VERSION:
        print(
            f"Nuitka {installed or 'not found'} or is older than "
            f"{'.'.join(map(str, MIN_NUITKA_VERSION))} — upgrading..."
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

    # Non-binary data only — see the module docstring, point 3, for why
    # TypeTreeGeneratorAPI/'s own DLLs are deliberately NOT in this list.
    site_packages = Path(sys.executable).resolve().parent / "Lib" / "site-packages"
    extra_data_dirs = [
        # (PROJECT_DIR / "UnityPy" / "resources", "UnityPy/resources"),
        (site_packages / "archspec", "archspec"),
    ]
    for src, _dest in extra_data_dirs:
        if not src.is_dir():
            raise SystemExit(f"expected folder not found: {src}")

    dll_config = Path(__file__).resolve().parent / "cli_onefile_dlls.nuitka-package.config.yml"
    if not dll_config.is_file():
        raise SystemExit(f"expected Nuitka package-config file not found: {dll_config}")

    cmd = [
        sys.executable, "-m", "nuitka",
        "--onefile",
        # See the module docstring, point 2 — the CLI's own import graph
        # should never reach PyQt6; this makes it a loud failure if it ever
        # does, instead of a silently Qt-bloated "CLI" build.
        "--nofollow-import-to=PyQt6",
        f"--windows-icon-from-ico={icon_path.resolve()}",
        # UnityPy.helpers.Tpk reads UnityPy/resources/lzma.tpk at module-init
        # time (a data file, not a traceable Python import) — same gap
        # build_GUI_portable.py already documents for the GUI build.
        "--include-package-data=UnityPy",
        # The vendored UnityPy is its own git repository: without this the .git folder (44 MB of history,
        # full of read-only files that also break Nuitka's own output cleanup) ships as "package data".
        "--noinclude-data-files=UnityPy/.git/*",
        # Other repository/editor leftovers that --include-package-data=UnityPy sweeps in.
        "--noinclude-data-files=UnityPy/.vscode/*",
        "--noinclude-data-files=UnityPy/.gitattributes",
        "--noinclude-data-files=UnityPy/classes/generated.py.backup",
        *[f"--include-data-dir={src}={dest}" for src, dest in extra_data_dirs],
        # English texts of core/'s messages (core/i18n.py): the CLI always runs in English. Only en.json.
        f"--include-data-files={PROJECT_DIR / 'locales' / 'en.json'}=locales/en.json",
        # The actual, confirmed-necessary fix for every native .dll/.exe this
        # build depends on (TypeTreeGeneratorAPI, UnityPy's bundled
        # bcn_encoder/fsb5_converter) — see the module docstring, point 3,
        # and the YAML file's own header comment for why --include-data-dir/
        # --include-package-data can never cover these regardless of how
        # they're invoked.
        f"--user-package-configuration-file={dll_config}",
        # A console app should always have a real console attached, even if
        # double-clicked directly rather than run from an existing
        # terminal — `shell` mode's whole REPL depends on stdin/stdout
        # actually being a console. The opposite choice from
        # build_GUI_portable.py's own --windows-console-mode=disable (a GUI
        # app hiding its console), for the opposite reason.
        "--windows-console-mode=force",
        "--assume-yes-for-downloads",
        # Same MSVC memory-pressure safety margin as build_GUI_portable.py —
        # see MIN_NUITKA_VERSION's own comment for why this file's
        # generated-C volume can still be large enough to matter.
        "--low-memory",
        "--jobs=2",
        # Cleans up Nuitka's own *.build/*.onefile-build intermediate cache
        # folders after a successful build, so dist-cli/ ends up holding
        # just the one deliverable exe — the whole point of a onefile build.
        "--remove-output",
        # Absolute path: the subprocess below runs with cwd=PROJECT_DIR
        # (UStudio/), so a relative "dist-cli" here would land at
        # UStudio/dist-cli instead of this script's own dist-cli/.
        f"--output-dir={DIST_DIR.resolve()}",
        f"--output-filename={APP_NAME}.exe",
        f"--product-name={DISPLAY_NAME}",
        f"--file-description={DISPLAY_NAME}",
        f"--company-name={AUTHOR}",
        f"--product-version={APP_VERSION}",
        f"--file-version={APP_VERSION}",
        str(ENTRY_POINT),
    ]

    print("Running:", " ".join(cmd))
    subprocess.run(cmd, cwd=PROJECT_DIR, check=True)
    strip_vcs_folders(DIST_DIR)   # no-op for a clean onefile build; guards against stray repos in dist-cli/

    project_docs_dir = Path(__file__).resolve().parent / "docs"
    copy_docs(DIST_DIR, CLI_DOCS, src_dir=project_docs_dir)

    copy_license_files(DIST_DIR)

    return DIST_DIR / f"{APP_NAME}.exe"


if __name__ == "__main__":
    out_path = build()
    print()
    print(f"Done. Portable CLI build: {out_path}")
    print(f"Run: {out_path}")
