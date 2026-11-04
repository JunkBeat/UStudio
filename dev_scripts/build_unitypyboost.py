"""
Compiles UStudio/UnityPyBoost/'s C++ sources (this project's own vendored,
LOCALLY PATCHED copy — see CLAUDE.md's "Real local patch applied to UnityPyBoost"
section for what's been fixed there and why) into a UnityPyBoost.<tag>.pyd for the
Python interpreter currently running this script, and drops it into
UStudio/UnityPy/ next to whatever .pyd(s) are already there.

This replaces the old dev_scripts/fetch_unitypyboost_pyd.py workflow for this
project: that script downloaded the OFFICIAL, VANILLA upstream build (prebuilt
wheel, or a source build from the official sdist) — neither carries this
project's local fix. Anything that needs the fix must be built from THIS folder's
sources, under each target Python, using this script instead. (fetch_unitypyboost_pyd.py
itself no longer exists in this checkout; if a future UnityPy version bump needs a
fresh vanilla baseline to diff against, re-fetch the sdist manually and re-apply the
local patch to the new TypeTreeHelper.cpp before running this script.)

Requires a working C++ toolchain for the running Python (on Windows: "Microsoft
C++ Build Tools" / Visual Studio with the "Desktop development with C++" workload
— this machine has it at C:\\BuildTools, installed specifically to build this
patch; see CLAUDE.md for the exact install command used).

Usage (run under the TARGET Python — the one you want a matching .pyd for):
    python dev_scripts/build_unitypyboost.py [--vcvarsall PATH_TO_vcvarsall.bat]

To (re)build for another Python version/architecture, install that interpreter,
then run this same script under IT (`py -3.11 dev_scripts/build_unitypyboost.py`,
etc.) — same one-script-per-target-interpreter model fetch_unitypyboost_pyd.py
used, just building from local patched sources instead of downloading.
"""
import argparse
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UNITYPYBOOST_SRC = PROJECT_ROOT / "UStudio" / "UnityPyBoost"
DEST_DIR = PROJECT_ROOT / "UStudio" / "UnityPy"

# Mirrors upstream UnityPy's own setup.py (K0lb3/UnityPy) build_ext subclass —
# fetched and confirmed when this project's local patch was first built, so a
# rebuild here produces object code equivalent to what upstream's own build
# process would produce, just from this project's patched sources.
_SETUP_PY = '''
import os
import re
import subprocess

from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext

INSTALL_DIR = os.path.dirname(os.path.realpath(__file__))
UNITYPYBOOST_DIR = os.path.join(INSTALL_DIR, "UnityPyBoost")


class BuildExt(build_ext):
    def build_extensions(self):
        cpp_version_flag: str
        compiler = self.compiler
        if compiler.compiler_type == "msvc":
            cpp_version_flag = "/std:c++20"
        elif compiler.compiler_type == "unix":
            res = subprocess.run([compiler.compiler[0], "-v"], capture_output=True)
            text = (res.stdout or res.stderr).decode("utf-8")
            version = re.search(r"version\\s+(\\d+)\\.", text)
            if version is None:
                raise Exception("Failed to determine compiler version")
            version = int(version.group(1))
            cpp_version_flag = "-std=c++2a" if version < 10 else "-std=c++20"
        else:
            cpp_version_flag = "-std=c++20"

        for ext in self.extensions:
            ext.extra_compile_args = [cpp_version_flag]

        build_ext.build_extensions(self)


setup(
    name="UnityPyBoostLocalBuild",
    ext_modules=[
        Extension(
            "UnityPyBoost",
            [f"UnityPyBoost/{f}" for f in os.listdir(UNITYPYBOOST_DIR) if f.endswith(".cpp")],
            depends=[f"UnityPyBoost/{f}" for f in os.listdir(UNITYPYBOOST_DIR) if f.endswith(".hpp")],
            language="c++",
            include_dirs=[UNITYPYBOOST_DIR],
        )
    ],
    cmdclass={"build_ext": BuildExt},
)
'''


def find_vcvarsall() -> Path:
    """Tries, in order: vswhere.exe (the portable, correct way — works regardless
    of where/which edition of VS or Build Tools is installed), then the exact path
    this machine's Build Tools were installed to as a last-resort fallback."""
    vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
    if vswhere.exists():
        result = subprocess.run(
            [str(vswhere), "-latest", "-products", "*",
             "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
             "-property", "installationPath"],
            capture_output=True, text=True,
        )
        install_path = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        if install_path:
            candidate = Path(install_path) / "VC" / "Auxiliary" / "Build" / "vcvarsall.bat"
            if candidate.exists():
                return candidate

    fallback = Path(r"C:\BuildTools\VC\Auxiliary\Build\vcvarsall.bat")
    if fallback.exists():
        return fallback

    sys.exit(
        "Could not find vcvarsall.bat (no VS/Build Tools installation detected). "
        "Install 'Microsoft C++ Build Tools' with the 'Desktop development with "
        "C++' workload, or pass --vcvarsall explicitly."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vcvarsall", help="Path to vcvarsall.bat (auto-detected if omitted)")
    parser.add_argument("--arch", default="x64", help="Target arch for vcvarsall (default: x64)")
    args = parser.parse_args()

    if not UNITYPYBOOST_SRC.is_dir():
        sys.exit(f"UnityPyBoost source folder not found: {UNITYPYBOOST_SRC}")

    vcvarsall = Path(args.vcvarsall) if args.vcvarsall else find_vcvarsall()
    if not vcvarsall.exists():
        sys.exit(f"vcvarsall.bat not found at: {vcvarsall}")

    print(f"Running under: {sys.version}")
    print(f"Platform tag: {sysconfig.get_platform()}-{sysconfig.get_python_version()}")
    print(f"vcvarsall: {vcvarsall} ({args.arch})")
    print(f"Source: {UNITYPYBOOST_SRC}")
    print(f"Destination: {DEST_DIR}\n")

    with tempfile.TemporaryDirectory() as tmp_str:
        build_dir = Path(tmp_str)
        shutil.copytree(UNITYPYBOOST_SRC, build_dir / "UnityPyBoost")
        (build_dir / "setup.py").write_text(_SETUP_PY, encoding="utf-8")

        cmd = (
            # DISTUTILS_USE_SDK/MSSdk: setuptools' own MSVC auto-detection (separate
            # from vcvarsall.bat, which only sets PATH/INCLUDE/LIB) tries to locate a
            # VS install itself via vswhere/registry and fails ("Unable to find a
            # compatible Visual Studio installation") for a non-standard install path
            # like this machine's C:\BuildTools — these two vars tell it to trust the
            # environment vcvarsall.bat already configured instead of re-detecting.
            'set DISTUTILS_USE_SDK=1 && set MSSdk=1 && '
            f'"{vcvarsall}" {args.arch} && '
            f'cd /d "{build_dir}" && '
            f'"{sys.executable}" setup.py build_ext --inplace'
        )
        # shell=True with the raw string (not an argv list passed to cmd.exe /c)
        # — subprocess's own argv-quoting rules double-quote an argument that
        # already contains embedded quotes, breaking vcvarsall's path here.
        result = subprocess.run(cmd, shell=True)
        if result.returncode != 0:
            sys.exit(f"Build failed (exit code {result.returncode}) — see compiler output above.")

        built = list(build_dir.glob("UnityPyBoost.*.pyd"))
        if not built:
            sys.exit("Build reported success but no UnityPyBoost.*.pyd was produced — unexpected.")
        if len(built) > 1:
            sys.exit(f"Expected exactly one built .pyd, found {len(built)}: {built}")

        target = DEST_DIR / built[0].name
        # Write next to the target then os.replace() into place (atomic rename)
        # instead of shutil.copy2() straight to target — a freshly-built .pyd can
        # get transiently locked (Windows Defender scanning a new executable is a
        # common cause) right after the linker closes it, and copy2 has no retry;
        # os.replace() also gives a clearer error if a RUNNING UStudio process has
        # the destination itself loaded (WinError 5, not 32).
        tmp_target = target.with_suffix(target.suffix + ".building")
        last_error = None
        for attempt in range(5):
            try:
                shutil.copy2(built[0], tmp_target)
                break
            except PermissionError as e:
                last_error = e
                time.sleep(1)
        else:
            sys.exit(f"Could not stage the built .pyd after several retries: {last_error}")
        os.replace(tmp_target, target)
        print(f"\nWrote: {target}")

    print(
        "\nDone. Restart any running UStudio process before testing — Windows "
        "keeps an already-loaded .pyd mapped in memory for a running process even "
        "after the file on disk is replaced (confirmed: os.replace() over it "
        "raises PermissionError/WinError 5 while the process is still running)."
    )


if __name__ == "__main__":
    main()
