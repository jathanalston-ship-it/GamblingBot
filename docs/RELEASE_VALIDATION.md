# Automated Release Validation

Every packaged build runs a **startup verification suite before publication**. The
release workflow launches the actual packaged application, confirms it starts, and
**only publishes if validation passes**. A release that cannot launch is never
published.

## The seven checks

Each is graded from the launched app's on-disk **startup report**
(`startup-report.json`, written by `desktop/electron/main.ts`; see
`docs/STARTUP_FORENSICS.md`), the backend's own report (`backend-startup.json`) and
a **live `/health` probe**:

| Check | Passes when |
|---|---|
| `electron_started` | the main process reached the `app-ready` stage |
| `backend_started` | the sidecar spawned and reached `healthy` |
| `health_endpoint` | a live `GET /health` returned HTTP 200 |
| `window_created` | the `create-window` stage executed (BrowserWindow built) |
| `renderer_loaded` | the `window-shown` stage fired (renderer painted) |
| `database_accessible` | the backend opened + reconciled the DB (`backend-startup.json` status `serving`) |
| `startup_report_generated` | the report exists and the run `completed` (reached `ready`) |

Validation passes only when **all seven** pass.

## What gets validated, and why the portable build

The workflow validates the **portable build** (`MomentumLab-Portable.zip`). Its
binaries are **byte-identical** to the installer's (the zip is just the unpacked
app — see `docs/PORTABLE_BUILD.md`), but it writes its state into
`MomentumLab-Data` beside the executable, so the **report location is
deterministic** — no install, no `%APPDATA%` lookup. Validating the portable build
therefore validates the release.

## Flow (`.github/workflows/release.yml`)

```
quality gate (ruff · mypy · tests · desktop build)   ← ubuntu
        │  (must pass)
        ▼
build_windows.ps1   → installer .exe + MomentumLab-Portable.zip   ← windows
        │
        ▼
Validate packaged build  ── launch the app, verify the 7 checks ──┐
        │  PASS → release-validation.json (ok:true)                │ FAIL
        ▼                                                          ▼
Create GitHub Release + upload assets            job fails → NOTHING is published
   (installer, portable zip, release-validation.json, update metadata)
```

The validation step runs **before** the publish step; if it fails, the job fails
and the publish step never runs. `release-validation.json` is attached to the
release as the proof-of-launch record.

## `release-validation.json`

```jsonc
{
  "validatedAt": "2026-06-21T…Z",
  "ok": true,
  "exe": "…/MomentumLab-Portable/Momentum Lab.exe",
  "appVersion": "0.0.47",
  "packaged": true,
  "portable": true,
  "healthUrl": "http://127.0.0.1:51234/health",
  "launchError": null,
  "checks": [ { "name": "electron_started", "ok": true, "detail": "reached stage \"ready\"" }, … ],
  "startupTimeline": [ { "stage": "module-init", … }, … ],
  "startupFailure": null,
  "backendStatus": "healthy"
}
```

## Implementation

| Piece | Where |
|---|---|
| Pure evaluator (`evaluateValidation`) + injectable runner (`runValidation`) | `desktop/scripts/release-validation.cjs` |
| CLI (`--exe`/`--out`/`--timeout`; real spawn/fetch/fs; exit 0/1) | `desktop/scripts/validate-release.cjs` (`npm run validate-release`) |
| Unit tests (all-pass, each failure mode, healthy run, never-launches, launch-throws) | `desktop/scripts/release-validation.test.cjs` (in `npm run test:backend`) |
| Gating step + asset upload | `.github/workflows/release.yml` |

The runner: cleans any prior `MomentumLab-Data`, launches the executable, polls for
the startup report until it reaches a terminal state (healthy / completed / failed)
or a timeout, probes `/health` on the port the app recorded, grades the checks,
writes `release-validation.json`, **always tears the app down** (`taskkill /T` on
Windows), and exits non-zero on any failure.

Run it locally against an extracted portable build:

```bash
node desktop/scripts/validate-release.cjs --exe "MomentumLab-Portable/Momentum Lab.exe"
```

## Notes / limitations

- Windows-only in CI (that's where the packaged build runs). The pure evaluator and
  the injected runner are unit-tested cross-platform (offline, no Electron).
- The timeout (default 180s in CI) must comfortably exceed PyInstaller's one-file
  extraction + uvicorn startup; a too-tight timeout would (safely) fail the gate.
- If the backend fails to start, the installer build pops a Retry/Quit modal that
  blocks; the validator simply times out and fails — the safe direction (no
  publish).
