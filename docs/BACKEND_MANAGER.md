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

## Tests

`desktop/scripts/backend-manager.test.cjs` (`npm run test:backend`, run in Desktop CI)
drives the manager with injected spawn/fetch/clock/delay — no Electron, no network —
covering: adopt-already-running (no spawn), cold start → healthy, start failure →
`failed`, graceful stop (SIGTERM), force after timeout (SIGKILL), crash → restart →
healthy, and "adopted backends are never killed." Dependency injection is what makes
the Electron lifecycle unit-testable in plain Node.
