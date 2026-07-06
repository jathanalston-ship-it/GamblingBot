# Automatic updates

Momentum Lab keeps itself up to date with **no manual steps**. The old sequence —
open the app, go to Updates, *Check*, *Download*, *Restart & install* — still
exists, but only as a **fallback**. The default path is automatic.

## The loop

1. **Releases build themselves on push.** Pushing to the repo's default branch
   (`claude/vigilant-wozniak-oueczq`) runs `.github/workflows/release.yml`, which
   passes the quality gate, builds the Windows installer, and publishes a GitHub
   Release with `latest.yml` + the installer + `*.blockmap` (the metadata
   electron-updater needs). The version is `pyproject.toml`'s if its tag is free,
   otherwise the next free patch bump above the highest existing tag — so every
   release is strictly newer and the updater always sees it. Put `[skip release]`
   in a commit message to push without cutting a release. (Tag pushes and manual
   *Run workflow* runs still work exactly as before.)

2. **The app scans on startup.** On every launch the packaged app silently checks
   the GitHub release feed (`electron/main.ts` → `initAutoUpdates` →
   `autoUpdater.checkForUpdates()`). The repository is **public**, so the feed is
   readable unauthenticated. Disable the launch check entirely with
   `MRP_DISABLE_AUTOUPDATE=1`.

3. **It downloads and installs automatically — after one confirmation.** When the
   check finds a newer release, the app raises a single prompt
   (`AutoUpdatePrompt.tsx`) showing:
   - the **new version**,
   - the **estimated download size** (summed from the release's artifact sizes),
   - the **recommended free disk space** to have available,

   so the user can plan. On **Update now** the update downloads, verifies its
   checksum, installs and restarts on its own — the full-screen `UpdateOverlay`
   narrates every step so the app never appears frozen. **Later** skips just this
   version (the app re-offers the next one); **Turn off automatic updates** falls
   back to the fully manual Updates screen.

## Sizing (what the prompt shows)

Pure, unit-tested logic in `electron/auto-update.ts`
(`scripts/auto-update.test.cjs`):

- **Download size** = sum of the release artifacts' `size` fields from
  `latest.yml` (bad/missing sizes are ignored; "unknown" when none are present).
- **Recommended free space** = `download + max(2 × download, 150 MB) + 250 MB`.
  It covers the downloaded installer (kept during install), the unpacked/installed
  app (~2× the compressed download, with a floor) and a safety margin, so an
  update can never fail halfway for lack of space. Conservative on purpose — it is
  advisory, shown so the user can plan.

## Preferences

Stored app-side as `update-prefs.json` next to the app's per-user state
(`electron/update-prefs.ts`), so the choice survives restarts and is readable even
when the backend is down (updates are an Electron-side concern):

| Field | Meaning | Default |
|---|---|---|
| `autoUpdate` | Master switch. When off, launch checks never prompt — the manual Updates screen is the only path. | `true` |
| `skippedVersion` | A version the user chose *Later* on; not re-prompted until a newer one appears. | `null` |

Toggle it from **Settings → Updates → Automatic updates**, or **Turn off
automatic updates** in the prompt itself.

## State machine & overlay

The whole journey is one explicit, clock-injectable `UpdateFlow`
(`electron/update-flow.ts`) streamed to the renderer. It now carries an
**`unattended`** flag: an automatic update is `unattended` from the moment the
user confirms, so `UpdateOverlay` narrates the **download → verify** phases too
(a *manual* download is watched inline on the Updates screen, so the overlay
stays hidden until the restart sequence). The flow serialises to a marker file
before `quitAndInstall()` and resumes after the installer restart, so the overlay
completes the same journey and `update-report.json` covers the whole thing —
including any operation over 250 ms.

## Fallback (manual) path

Unchanged and always available on the **Updates** screen: *Check again* →
*Download update* (inline progress) → *Restart & install*, plus the live feed
diagnostics. A downloaded update also installs on the next quit
(`autoInstallOnAppQuit`). In a source/dev install the screen falls back to the
git-based self-update (`/update/*`). See `docs/WINDOWS_INSTALLER.md` §10 and
`docs/AUTO_UPDATE_AUDIT.md`.
