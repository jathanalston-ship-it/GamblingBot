# Development Mode

Rapid local testing of the desktop app **without rebuilding the installer**. One
command runs Electron + the FastAPI backend from source with hot reload, a visible
banner, and a Developer Panel for inspecting and driving startup/shutdown.

```bash
cd desktop
npm install        # first time only
npm run dev-app
```

## What `dev-app` does

`npm run dev-app` runs two processes (via `concurrently`):

1. **`dev:renderer`** — the Vite dev server on `:5173` (React **frontend hot reload** /
   HMR — edits to `.tsx`/`.css` apply instantly).
2. **`dev-app:electron`** — waits for Vite, compiles the Electron main/preload
   (`build:electron`), then launches Electron with `NODE_ENV=development` and
   `MRP_DEV_APP=1`.

In that Electron process:

- **Electron runs from source** — the main process loads the renderer from
  `http://localhost:5173` (not a packaged bundle).
- **The backend runs from source** — `BackendManager` spawns
  `python -m momentum.api` (set `MRP_PYTHON` to choose the interpreter), with
  `PYTHONPATH=<repo>/src`.
- **Backend auto-restart on code changes** — a recursive watch on
  `src/momentum/**/*.py` restarts the backend (debounced, via
  `BackendManager.restart()`) and reloads the renderer when a `.py` file changes.
- **Isolated state** — DB, logs and editable settings live under a git-ignored
  `<repo>/.dev/` (`data/`, `logs/`, `settings.yaml`/`.env`), so dev runs never
  touch your real `%APPDATA%`/userData install. Delete `.dev/` for a clean slate.
- **A persistent "DEVELOPMENT MODE" banner** is shown across the top of every
  screen, with a link to the Developer Panel.

Plain `npm run dev` is unchanged (no dev-app features, no isolated `.dev` state).

## The Developer Panel

A dev-only screen (nav item **Developer**, route `/developer`; the banner links to
it). It **auto-refreshes** every 2 s.

**Diagnostics**

| Field | Source |
|---|---|
| Backend PID | `BackendManager` (the spawned process) |
| Backend status | lifecycle status: starting / healthy / failed / restarting / stopped |
| Health endpoint | live `GET /health` probe from the renderer |
| Startup stage | the live `StartupTrace` stage (see `docs/STARTUP_FORENSICS.md`) |
| Database path | `DATABASE_URL` (the `.dev` SQLite file) |
| Config path | `MRP_USER_DIR` (where `settings.yaml`/`.env` live) |
| Log path | `MRP_LOG_DIR` |
| Current branch | parsed from `<repo>/.git/HEAD` |
| Current version | `app.getVersion()` |

**Controls**

| Button | Action |
|---|---|
| Restart Backend | `BackendManager.restart()` + reload the renderer |
| Reload Renderer | `webContents.reloadIgnoringCache()` |
| Open Logs Folder | reveal `.dev/logs` |
| Open Database Folder | reveal `.dev/data` |
| Seed Demo Data | `POST /actions/seed-demo` (polled job) |
| Reset Local Data | `POST /actions/reset` (confirm-gated) |
| Run Health Audit | `GET /health/routes` (per-route live probe) |
| Export Diagnostic Bundle | writes `logs/diagnostic-bundle-<ts>/` (summary + startup/backend reports + `mrp.log`) and reveals it |

## Failure handling — never a silent exit

Building on the startup forensics work (`docs/STARTUP_FORENSICS.md`), Development
Mode guarantees a failure is always visible and recoverable:

- The whole `whenReady` startup is guarded; a fatal error is traced, reported and
  surfaced — never a silent `process.exit`.
- If the **backend fails to start** under `dev-app`, the launcher does **not** pop a
  blocking modal or quit. The window stays up and `BackendGate` renders the
  **Developer Panel** (instead of a dead loading screen), showing the failed status,
  the unreachable health probe and the captured startup stage/failure.
- The source-watcher stays armed even after a failed start, so **fixing the code and
  saving** brings the backend up and reloads the UI. The **Restart Backend** button
  does the same on demand.

## Implementation

| Piece | Where |
|---|---|
| `dev-app` / `dev-app:electron` scripts | `desktop/package.json` |
| Dev flag, isolated `.dev` paths, source-watcher, dev IPC, diagnostics, bundle export | `desktop/electron/main.ts` |
| `BackendManager.restart()` | `desktop/electron/backend-manager.ts` |
| `window.mrp.dev` + `window.mrp.devtools` bridge | `desktop/electron/preload.ts` |
| DEVELOPMENT MODE banner | `desktop/renderer/src/components/DevBanner.tsx` |
| Developer Panel | `desktop/renderer/src/views/Developer.tsx` |
| Failure fallback to the panel | `desktop/renderer/src/components/BackendGate.tsx` |

Tested in `desktop/scripts/backend-manager.test.cjs` (`restart()` stops the old
backend and spawns a fresh one) and the existing startup-trace / smoke suites.
