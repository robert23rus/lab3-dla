"""Create a portable ZIP without the environment, caches or working results.

python scripts/package_project.py --verify
Verification extracts the ZIP into a fresh temporary directory and audits that
copy, using the current Python environment. The source project is not changed.
"""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    output = ROOT.parent / (ROOT.name + ".zip")
    entries = []
    for current, directories, files in os.walk(ROOT):
        current = Path(current)
        directories[:] = [name for name in directories
                           if name not in {".venv", ".git", "__pycache__", ".pytest_cache"}
                           and not (current == ROOT and name.startswith("results"))]
        for name in files:
            path = current / name
            if name.startswith("~$") or path.suffix.lower() in {".pyc", ".pyo", ".nbc", ".nbi", ".tmp"}:
                continue
            entries.append(path)
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(entries):
            archive.write(path, Path(ROOT.name) / path.relative_to(ROOT))
    with ZipFile(output) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f"Corrupt ZIP member: {bad}")
        if args.verify:
            temporary = Path(tempfile.mkdtemp(prefix="codex-lab3-release-"))
            archive.extractall(temporary)
            extracted = temporary / ROOT.name
            subprocess.run([sys.executable, str(extracted / "scripts/check_project.py")],
                           cwd=extracted, check=True)
    print(f"ZIP: {output}\nFiles: {len(entries)}\nSize: {output.stat().st_size / 1024**2:.2f} MiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
