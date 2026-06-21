# Backend Process Manager

Electron owns the FastAPI backend lifecycle through a single `BackendManager`
(`desktop/electron/backend-manager.ts`). `main.ts` is a thin host: it builds the
manager, forwards its status to the renderer, and drives quit.

## Launch

1. **Check if a backend is already running** — `probeHealth()` hits `GET /health`
   once. If a backend answers (a leftover sidecar or a dev server), it is **adopted**
   (used as-is, never killed/restarted by us).
2. **Else start it** — spawn the bundled binary / `python -m momentum.api`, capturing
   stdout+stderr.
3. **Wait for `/health`** — poll until healthy, the process exits (fail fast), or the
   per-attempt timeout; retry up to `startAttempts`.
4. **Loading screen until healthy** — the manager emits status; the renderer's
   `BackendGate` shows a loading screen and only renders the app once `healthy`.

## Status (displayed by the renderer)

`starting` · `healthy` · `failed` · `restarting` · `stopped`

main forwards every transition over `mrp:backend:status` (and `mrp:backend:get-status`
to seed on mount). `BackendGate` maps them to **Backend Starting / Healthy / Failed /
Restarting** overlays; the app is gated until `healthy`, so screens never fetch
against an unready backend.

## Crash recovery

If a backend that was healthy exits unexpectedly, the manager emits `restarting`,
respawns (bounded by `maxRestarts`), and on success emits `healthy` + a `restarted`
event (main reloads the window so stale errors clear). Exhausting the cap emits a
`give-up` event → main shows a Retry/Quit dialog.

## Shutdown

1. **Graceful signal** — `taskkill /T` (Windows) or `SIGTERM` (POSIX) to the tree.
2. **Wait** — up to `shutdownTimeoutMs` (5 s).
3. **Force** — `taskkill /T /F` / `SIGKILL` on the whole tree.

`will-quit` `preventDefault()`s and defers exit until `stop()` completes. Adopted
backends are never killed. Synchronous safety nets (`forceKillSync`) run on
`process.exit` / `uncaughtException` / signals; the backend's parent watchdog
(`momentum/api/parent_watchdog.py`) covers hard-kill / system-shutdown paths.

## Logging

Every status transition and all captured backend output is logged through an injected
`log` callback (main wires it to `console.error("[backend-manager] …")`, inherited by
Electron's stdout; the Python backend additionally writes `mrp.log`). The last
`logTailLines` of output back the failure dialog so the cause is visible.

## Startup diagnostic report

Every launch attempt writes two JSON records under the log directory
(`%APPDATA%\momentum-lab-desktop\logs` on Windows) so a failed install is
diagnosable from disk with **zero terminal interaction**:

- **`startup-report.json`** (authoritative, written by `main.ts` after each
  `start()`) — the launcher's view: backend **executable path**, **PID**, start →
  healthy **duration**, final **health status**, whether a running backend was
  **adopted**, attempt count, the **database URL** and **log dir** the backend was
  launched with, the `/health` URL, and the tail of any startup **exception**
  (`manager.diagnostics`).
- **`backend-startup.json`** (written by the backend itself,
  `momentum/api/startup_report.py`) — the backend's view: which **executable** is
  actually running (frozen or not), its **PID**, the **configuration loaded**
  (host/port/log dir/user dir/parent PID), the **database path** it opened, and
  any **startup exception** it raised before serving (`status: serving | failed`).

Together they answer "what ran, with what config, against which database, how
long it took, and — if it failed — exactly why," without attaching a terminal.
The Retry/Quit failure dialog shows the same captured exception inline.

## Tests

`desktop/scripts/backend-manager.test.cjs` (`npm run test:backend`, run in Desktop CI)
drives the manager with injected spawn/fetch/clock/delay — no Electron, no network —
covering: adopt-already-running (no spawn), cold start → healthy, start failure →
`failed`, graceful stop (SIGTERM), force after timeout (SIGKILL), crash → restart →
healthy, "adopted backends are never killed," and the **startup diagnostics**
(cold-start records executable/PID/duration, an adopted backend reports a null PID,
a failed start captures an error tail). Dependency injection is what makes the
Electron lifecycle unit-testable in plain Node. The backend-side report writer is
covered by `tests/unit/api/test_startup_report.py`.

## Verification matrix

Each requirement of the "fully automatic backend lifecycle, zero terminal" goal,
and the automated proof that backs it:

| Requirement | Mechanism | Proof |
|---|---|---|
| Auto-launch (user never runs `python -m momentum.api`) | `manager.start()` spawns `backendCommand()` in `whenReady` | `cold start spawns and reaches healthy` |
| Adopt an already-running backend | `probeHealth()` before spawning | `adopts an already-running backend without spawning` |
| Health responds before the UI is usable | `BackendGate` gates the app on `healthy` | `did-finish-load` re-sends status; `records startup diagnostics` |
| UI waits (loading screen) | renderer `BackendGate` overlay per status | desktop typecheck + smoke boot |
| Backend survives startup / retries | bounded spawn retries + crash recovery | `reports failed…`, `recovers (restart)…` |
| Logs written to disk | `mrp.log` + `startup-report.json` + `backend-startup.json` | `test_startup_report.py`, `diagnostics capture an error tail` |
| Clean shutdown, no orphans | graceful → wait → force tree-kill + parent watchdog | `graceful stop…`, `force-kills the tree…`, `test_parent_watchdog.py` (real no-orphan test) |
| Diagnosable failure (exact exception) | captured stderr → dialog + reports | `diagnostics capture an error tail`, `__main__` writes `failed` report |
