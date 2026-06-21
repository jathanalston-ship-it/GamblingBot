# Momentum Lab — Windows Installation Package

A production, double-click installer for **Windows 11**, built for a
**non-technical** user. No Python, no Node, no command line.

## End-user experience (the goal)

1. **Download** `MomentumLab-Setup-<version>.exe`.
2. **Double-click** it → a small wizard (Welcome → Install → Finish).
3. **Launch Momentum Lab** from the desktop icon (or the tick on the Finish page).

No administrator prompt (per-user install). The app opens its own window; the
database and logs are created automatically in the user's profile.

---

## 1. Installer architecture

```
MomentumLab-Setup.exe  (NSIS, per-user)
└── installs to  %LOCALAPPDATA%\Programs\Momentum Lab\
    ├── Momentum Lab.exe            ← Electron shell (the app the user launches)
    ├── resources\
    │   ├── app.asar                ← UI (renderer) + Electron main process
    │   └── backend\
    │       └── mrp-backend.exe     ← frozen FastAPI backend (PyInstaller, no Python needed)
    └── (uninstaller registered in Windows "Apps & features")

At runtime:
  Momentum Lab.exe ──spawns──▶ mrp-backend.exe  (loopback http://127.0.0.1:<free port>)
        │                              │
        └── waits for /health ◀────────┘  then shows the window

User data (writable, survives reinstall):
  %APPDATA%\Momentum Lab\data\momentum.db     ← SQLite database (trade ledger, audit)
  %APPDATA%\Momentum Lab\logs\                ← rotating logs
```

Two processes, both **loopback-only** — nothing is exposed to the network. The
Electron main picks a **free TCP port** at launch, so a busy port 8000 never
blocks startup, and writes the DB/logs under `%APPDATA%` (never under Program
Files, which is read-only for a per-user install).

## 2. Required dependencies

**End user:** none. Windows 11 only. The installer bundles everything (Chromium
via Electron + the frozen Python backend).

**Build machine** (whoever produces the installer — Windows 11 or Windows CI):

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.12+ | freeze the backend (PyInstaller) |
| Node.js + npm | 18+ | build the UI + run electron-builder |
| (auto-installed by the script) PyInstaller, Pillow, electron, electron-builder | — | packaging toolchain |

> Cross-building a Windows `.exe` from macOS/Linux is **not supported** here:
> PyInstaller cannot cross-compile, so the backend must be frozen on Windows.
> Run the build on Windows (or a `windows-latest` CI runner).

## 3. Build process (one command)

On a Windows 11 machine with Python and Node installed:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

This script (`scripts/build_windows.ps1`):

1. **Freezes the backend** — creates a build venv, installs the project, and runs
   PyInstaller (`desktop/build/backend.spec`) → `desktop/build/backend/mrp-backend.exe`.
2. **Builds the desktop app** — `npm ci` then `npm run build` (renderer via Vite →
   `renderer/dist`, Electron main via tsc → `dist-electron`).
3. **Packages the installer** — `electron-builder --win` → `desktop/release/MomentumLab-Setup-<version>.exe`.
4. **Builds the portable zip** — zips the unpacked app (+ a portable marker) →
   `desktop/release/MomentumLab-Portable.zip` (no-install build for testing release
   candidates; see `docs/PORTABLE_BUILD.md`).

Both artifacts are printed at the end and live in `desktop/release/`.

## 4. Packaging process (what electron-builder does)

Driven by `desktop/electron-builder.yml`:

- Packs `dist-electron/**` (main/preload) and `renderer/dist/**` (UI) into `app.asar`.
- Ships `desktop/build/backend/` as `resources/backend/` (`extraResources`).
- Generates the NSIS installer, the uninstaller, and the shortcuts.
- `publish: null` — **no update feed**; the artifact is standalone (auto-updates
  are intentionally out of scope for this milestone).

## 5. Windows installer generation (NSIS settings)

From `electron-builder.yml → nsis`:

| Setting | Value | Effect |
|---|---|---|
| `oneClick` | `false` | a friendly wizard, not a silent flash |
| `perMachine` | `false` | per-user install → **no admin/UAC prompt** |
| `allowToChangeInstallationDirectory` | `true` | user may pick a folder |
| `runAfterFinish` | `true` | "Launch Momentum Lab" checkbox on the last page |
| `createDesktopShortcut` | `always` | see §6 |
| `createStartMenuShortcut` | `true` | see §6 |

## 6. Desktop shortcut generation

NSIS creates both shortcuts automatically, named **Momentum Lab** (`shortcutName`),
pointing at `Momentum Lab.exe` with the app icon:

- **Desktop:** `Desktop\Momentum Lab.lnk`
- **Start Menu:** `Start Menu\Programs\Momentum Lab.lnk`

The uninstaller removes both.

## 7. Application icon support

- **Source:** `desktop/build/make_icon.py` (Pillow) renders the mark — an upward
  momentum bar chart — and emits:
  - `desktop/build/icon.ico` (multi-resolution 16–256 px) → Windows app + installer chrome.
  - `desktop/build/icon.png` (1024 px) → macOS/Linux + favicon source.
- **Wiring:** `win.icon`, `nsis.installerIcon`, `uninstallerIcon`,
  `installerHeaderIcon` all point at `build/icon.ico`. The window title bar and
  taskbar use the same icon. Regenerate with `npm run icon` (in `desktop/`) or
  `python desktop/build/make_icon.py`.

## 8. Uninstall support

- Registered in **Settings → Apps → Installed apps → Momentum Lab → Uninstall**
  (and Control Panel "Programs and Features").
- The uninstaller removes the app, both shortcuts, and the registry entry.
- **User data is preserved by default** (`deleteAppDataOnUninstall: false`) so a
  reinstall keeps the trade ledger; it lives in `%APPDATA%\Momentum Lab\` and can
  be deleted by hand. Flip the flag to `true` to wipe data on uninstall.

## 9. Startup verification checklist

After installing on a clean Windows 11 machine, verify:

- [ ] `MomentumLab-Setup-<version>.exe` runs **without** SmartScreen blocking it
      outright (unsigned builds show "More info → Run anyway"; see Notes).
- [ ] Installer completes with **no administrator prompt**.
- [ ] A **Desktop** shortcut "Momentum Lab" exists with the app icon.
- [ ] A **Start Menu** entry "Momentum Lab" exists.
- [ ] Launching shows the splash/window within ~10–30 s (first launch creates the DB).
- [ ] The window title bar and taskbar show the **Momentum Lab icon**.
- [ ] The Dashboard renders (empty is fine on a fresh install; seed via the app is optional).
- [ ] `%APPDATA%\Momentum Lab\data\momentum.db` exists after first launch.
- [ ] `%APPDATA%\Momentum Lab\logs\` contains a log file.
- [ ] Closing the window exits the app **and** stops `mrp-backend.exe`
      (check Task Manager — no orphaned process).
- [ ] Re-launching opens a single instance (no second backend; Task Manager shows one).
- [ ] **Uninstall** removes the app + shortcuts; data folder remains (by design).

## 10. Automated releases (GitHub Releases CI/CD)

`.github/workflows/release.yml` builds and publishes the installer. Trigger it
**either** way:

**A — push a version tag** (creates the release for that tag):

```bash
# bump the version first (pyproject.toml + desktop/package.json), commit, then:
git tag v0.0.23
git push origin v0.0.23
```

**B — run it from the Actions tab** (no tag needed): open **Actions → Release →
Run workflow**, pick the branch, and optionally enter a version (blank = use
`pyproject.toml`). The workflow creates the `v<version>` tag and the release from
that branch's latest commit. (This is the easy path if you're not working from a
local clone — don't pass a tag that doesn't exist yet, or checkout will fail.)

The workflow:

1. **Quality gate** (Ubuntu) — `ruff` + `mypy --strict` + `pytest` + the desktop
   `typecheck`/`build`. **If any fail, no release is produced.**
2. **Build** (Windows) — runs `scripts/build_windows.ps1` (the same one-command
   build), after syncing `desktop/package.json` to the release version so the
   installer and the version baked into the app match.
3. **Publish** — creates the tag (if needed) + GitHub Release, generates notes
   from the git commits since the previous tag, and uploads
   `MomentumLab-Setup-<version>.exe` (plus `latest.yml` + `*.blockmap` for
   auto-update).

## Notes / known limitations

- **Code signing:** initial builds are **unsigned**, so Windows SmartScreen will
  warn on first run ("Windows protected your PC" → *More info* → *Run anyway*).
  Signing is **opt-in and requires no config change** — set the encrypted CI
  secrets `CSC_LINK` (base64 `.pfx`) and `CSC_KEY_PASSWORD` and electron-builder
  signs automatically (placeholders documented in `electron-builder.yml`).
- **Auto-updates:** the packaged app has **working in-app updates**.
  `electron-builder.yml` declares a GitHub `publish` feed (generates `latest.yml`),
  `electron/main.ts` wires `electron-updater` (checks the feed on launch + over
  IPC), and the **Updates screen** drives it: it shows the installed/latest
  versions and a *Check again* → *Download update* (with progress) → *Restart &
  install* flow. When the launch check finds a newer version, a subtle badge
  appears on the **Updates** nav item and in the **context bar** (click → Updates).
  A downloaded update also installs on the next quit. In a source/dev install the
  same screen falls back to the git-based self-update (`/update/*`). Updates work on
  unsigned Windows builds (integrity is verified via the sha512 in `latest.yml`);
  signing is still recommended to avoid SmartScreen. Disable the launch check with
  `MRP_DISABLE_AUTOUPDATE=1`.
- **First launch** is the slowest (PyInstaller unpacks the backend and the DB is
  created); subsequent launches are fast.
- **Live trading** is out of scope — Momentum Lab is paper/research only.

## Troubleshooting

- **"Momentum Lab cannot be closed" during install (with no Momentum Lab in Task
  Manager):** the offender is the **backend sidecar `mrp-backend.exe`** (which runs
  from inside the install dir), not the app itself. The app now kills the whole
  backend process **tree** on every shutdown path (`stopBackend` → `taskkill /T`),
  so it should not orphan; if you still hit it, end `mrp-backend.exe` (and any
  `Momentum Lab.exe`) under Task Manager → **Details**, or just **reboot** and run
  the installer before opening the app.
