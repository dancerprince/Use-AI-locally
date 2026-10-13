# PyInstaller spec: standalone one-folder build (no Python needed on the target).
# Build from the repo root after bundling the UI:
#   cd frontend && npm run build:bundle && cd ..
#   uv run --project backend --with pyinstaller pyinstaller packaging/offline-ai.spec
# Output: dist/offline-ai/offline-ai[.exe]
# ruff: noqa
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent
APP = ROOT / "backend" / "app"

datas = [(str(APP / "static"), "app/static"), (str(APP / "catalog.json"), "app")]
binaries = []
hidden = collect_submodules("app") + collect_submodules("uvicorn")
for pkg in ("mcp", "sqlmodel", "pydantic_settings", "platformdirs", "rich"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden += h

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "backend")],
    datas=datas,
    binaries=binaries,
    hiddenimports=hidden,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="offline-ai", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="offline-ai")
