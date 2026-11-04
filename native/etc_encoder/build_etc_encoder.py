"""Builds etc_encoder.dll (ETC1 / ETC2 encoder, see etc_encoder.cpp) with MSVC
and puts it into UStudio/UnityPy/resources/etc_encoder/.

    python native/etc_encoder/build_etc_encoder.py [--vcvars PATH]

Static CRT (/MT): the DLL needs nothing but Windows itself.
etcpack/ is etcpack 2.74 as shipped in AMD Compressonator
(cmp_compressonatorlib/etc/etcpack, commit 095a143ad8cf), unchanged.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE.parent.parent / "UStudio" / "UnityPy" / "resources" / "etc_encoder"
DEFAULT_VCVARS = r"C:\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
SOURCES = ["etc_encoder.cpp", "etcpack/etcpack.cxx", "etcpack/etcimage.cxx", "etcpack/etcdec.cxx"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vcvars", default=DEFAULT_VCVARS)
    args = parser.parse_args()
    if not os.path.isfile(args.vcvars):
        print(f"vcvars64.bat not found: {args.vcvars}")
        return 1
    # MSBuild-free, but cl still trips over very long paths: build in a short temp folder.
    with tempfile.TemporaryDirectory(prefix="etcb") as work:
        sources = " ".join(f'"{HERE / s}"' for s in SOURCES)
        cl = (
            f'cl /nologo /O2 /EHsc /MT /LD /W1 /wd4996 /I"{HERE / "etcpack"}" {sources} '
            f'/Fe"{work}\\etc_encoder.dll" /Fo"{work}\\\\" /link /NOLOGO'
        )
        result = subprocess.run(f'"{args.vcvars}" >nul && {cl}', shell=True, cwd=work)
        if result.returncode:
            return result.returncode
        TARGET.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(work) / "etc_encoder.dll", TARGET / "etc_encoder.dll")
    print(f"Built {TARGET / 'etc_encoder.dll'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
