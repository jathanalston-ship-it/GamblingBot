# PyInstaller spec — freeze the FastAPI backend into a standalone one-file binary.
#
# Run from the REPOSITORY ROOT (paths below are repo-root relative):
#
#     pyinstaller --noconfirm \
#         --distpath desktop/build/backend \
#         --workpath desktop/build/.pyiwork \
#         desktop/build/backend.spec
#
# Output: desktop/build/backend/mrp-backend(.exe) — the sidecar the Electron main
# process spawns in a packaged build. No Python is required on the user's machine.

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# The momentum package loads submodules dynamically (e.g. persistence.models
# imports every model); uvicorn loads its loops/protocols/lifecycle lazily.
hidden = collect_submodules("momentum") + collect_submodules("uvicorn")

# Ship the example YAML configs so the Settings view has defaults to read.
datas = collect_data_files("momentum")
datas += [("config", "config")]

block_cipher = None

a = Analysis(
    ["src/momentum/api/__main__.py"],
    pathex=["src"],
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
