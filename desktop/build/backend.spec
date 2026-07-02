# PyInstaller spec — freeze the FastAPI backend into a standalone one-file binary.
#
# Paths below are anchored to the repository root via SPECPATH, so it can be
# invoked from anywhere. The canonical invocation is from the repo root:
#
#     pyinstaller --noconfirm \
#         --distpath desktop/build/backend \
#         --workpath desktop/build/.pyiwork \
#         desktop/build/backend.spec
#
# Output: desktop/build/backend/mrp-backend(.exe) — the sidecar the Electron main
# process spawns in a packaged build. No Python is required on the user's machine.

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# PyInstaller resolves relative paths in a spec relative to the spec file's own
# directory (SPECPATH), NOT the working directory. This spec lives in
# desktop/build/, so anchor every path to the repository root (two levels up)
# to stay correct regardless of where pyinstaller is invoked from.
REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

# The momentum package loads submodules dynamically (e.g. persistence.models
# imports every model); uvicorn loads its loops/protocols/lifecycle lazily.
hidden = collect_submodules("momentum") + collect_submodules("uvicorn")

# Ship the example YAML configs so the Settings view has defaults to read.
datas = collect_data_files("momentum")
datas += [(os.path.join(REPO_ROOT, "config"), "config")]

# zoneinfo needs the IANA database on Windows (no system tzdb). zoneinfo pulls
# tzdata lazily via importlib.resources, which static analysis can't see — so
# collect the package + its zone files explicitly for the market daemon's
# US/Eastern schedule.
try:
    datas += collect_data_files("tzdata")
    hidden += ["tzdata"]
except Exception:  # tzdata not installed (non-Windows dev build) — zoneinfo uses the OS tzdb
    pass

block_cipher = None

a = Analysis(
    [os.path.join(REPO_ROOT, "src", "momentum", "api", "__main__.py")],
    pathex=[os.path.join(REPO_ROOT, "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PySide6"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="mrp-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # no console window flashes on a non-technical user's screen
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
