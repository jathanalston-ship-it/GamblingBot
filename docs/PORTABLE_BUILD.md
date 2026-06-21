# Portable Build — `MomentumLab-Portable.zip`

A **no-install** Windows build for testing release candidates fast: download the
zip, extract, run the executable. No installer, no registry entries, no uninstall
process. It ships the same binaries as the installer, so it **behaves identically**
— only the location of writable state differs.

## What the user does

1. Download `MomentumLab-Portable.zip` from the GitHub Release.
2. Extract it anywhere (Downloads, Desktop, a USB stick).
3. Run **`Momentum Lab.exe`** inside the extracted `MomentumLab-Portable` folder.

To "uninstall": delete the folder. To reset: delete `MomentumLab-Data` beside the
executable.

## What's in the zip

The fully-unpacked app electron-builder produces (`win-unpacked`), plus a marker:

```
MomentumLab-Portable/
├─ Momentum Lab.exe            ← the Electron executable (run this)
├─ MomentumLab.portable        ← marker → portable mode (see below)
├─ resources/
│  ├─ app.asar                 ← the bundled renderer + Electron main
│  └─ backend/mrp-backend.exe  ← the frozen FastAPI backend
├─ *.dll, *.pak, locales/, …   ← the Electron runtime
└─ MomentumLab-Data/           ← created on first run (DB, logs, settings)
```

## Portable mode — logs beside the executable

The only behavioural difference from the installer is **where writable state
lives**. The launcher resolves its data root by mode (`desktop/electron/paths.ts`,
`resolveDataRoot`):

| Mode | Data root |
|---|---|
| Development (`npm run dev-app`) | `<repo>/.dev` |
| **Portable (this build)** | **`<exeDir>/MomentumLab-Data`** (beside the exe) |
| Installed | per-user `%APPDATA%\Momentum Lab` (userData) |

Portable mode is detected by the **`MomentumLab.portable` marker file** shipped
beside the executable (present only in the zip, never in the installer) — or by
electron-builder's own `PORTABLE_EXECUTABLE_DIR` env var. In portable mode the
database, **startup logs** (`logs/mrp.log`, `logs/startup-report.json`,
`logs/backend-startup.json`), and editable settings are all written to
`MomentumLab-Data` next to the executable — nothing touches `%APPDATA%` or the
registry. This makes a release candidate fully self-contained and trivially
diagnosable (the startup diagnostic report sits right beside the exe; see
`docs/STARTUP_FORENSICS.md`).

Everything else — backend spawn, health gating, crash recovery, the UI, the
startup trace — is the same code path as the installer, so the portable build is a
faithful test of the release.

## How it's built (CI)

No second electron-builder target: the installer build already leaves the unpacked
app in `desktop/release/win-unpacked`. `scripts/build_windows.ps1` step 4:

1. copies `win-unpacked` → `MomentumLab-Portable`,
2. writes the `MomentumLab.portable` marker beside `Momentum Lab.exe`,
3. `Compress-Archive` → `desktop/release/MomentumLab-Portable.zip`.

The release workflow (`.github/workflows/release.yml`) uploads
`MomentumLab-Portable.zip` to the GitHub Release alongside the installer, on every
`v*` tag (or manual dispatch). Because the binaries are byte-identical to the
installer's, the two artifacts can't drift.

## Verification

- `resolveDataRoot` is unit-tested (`desktop/scripts/paths.test.cjs`): portable →
  beside the exe; installed → userData; dev-app wins over portable.
- `startup-report.json` and the Developer Panel both report a `portable` flag, so a
  given run's mode is self-evident on disk and in the UI.

## Notes / limitations

- In-app auto-update (electron-updater) targets the **installer** feed; in a
  portable build a launch-time update check simply finds nothing applicable and is
  surfaced as a non-fatal event (it never rewrites the extracted folder). Use the
  portable zip for testing a specific candidate, the installer for the auto-updating
  install.
- Windows only (matching the rest of the desktop packaging; PyInstaller can't
  cross-compile the backend).
