#!/usr/bin/env python3
"""Build a distributable release: bundle the UI into the Python package, then build wheel + sdist.

Usage:  python scripts/build_release.py [--skip-frontend]
Output: backend/dist/offline_ai-<version>-py3-none-any.whl (+ .tar.gz)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
BACKEND = ROOT / "backend"


def run(cmd: list[str], cwd: Path) -> None:
    print(f"$ {' '.join(cmd)}  (in {cwd.name})", flush=True)
    exe = shutil.which(cmd[0])
    if not exe:
        sys.exit(f"Required tool not found on PATH: {cmd[0]}")
    subprocess.run([exe, *cmd[1:]], cwd=cwd, check=True)  # noqa: S603


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-frontend", action="store_true")
    args = ap.parse_args()

    if not args.skip_frontend:
        run(["npm", "ci"], FRONTEND)
        run(["npm", "run", "build:bundle"], FRONTEND)
    if not (BACKEND / "app" / "static" / "index.html").is_file():
        sys.exit("backend/app/static/index.html missing; build the frontend first.")

    shutil.rmtree(BACKEND / "dist", ignore_errors=True)
    run(["uv", "build"], BACKEND)
    for f in sorted((BACKEND / "dist").iterdir()):
        print(f"built {f.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
