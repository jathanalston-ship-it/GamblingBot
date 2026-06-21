# Packaged Startup — Forensic Audit

**Symptom (reported):** after the backend-lifecycle changes, launching the packaged
app shows a blue "busy" cursor for a moment, then **no window, no visible app, and
no persistent process**. The installer builds, installs and the shortcut works; the
app *used* to launch.

**Verdict:** the lifecycle commits did not break the *backend* — they made the
**Electron main process able to terminate before the window is shown, silently,
with nothing written to disk.** This document traces the complete packaged startup
path, names the failure conditions at every stage, identifies the exact mechanism,
and documents the instrumentation + fix added in `desktop/electron/`.

> Scope: diagnosis + logging/observability + the minimal fix for the silent
> termination. No features, no architecture change — same loopback-sidecar model.

---

## 1. The complete packaged startup path

The packaged launch (`app.isPackaged === true`, `NODE_ENV` unset, `MRP_SMOKE` unset)
runs entirely in `desktop/electron/main.ts`:

```
OS runs Momentum Lab.exe (Electron)
  └─ main process module loads  ─────────────────────────────── [module-init]
       ├─ globals, then app.requestSingleInstanceLock() ──────── [single-instance-lock]
       │     └─ lock NOT acquired → app.quit() (exit, no window)   ← legitimate
       └─ app.whenReady().then(startup)                          ── [app-ready]
            ├─ apiPort = await freePort()                        ── [free-port]
            ├─ set MRP_API_PORT / MRP_APP_VERSION / MRP_PACKAGED ── [configure-env]
            ├─ manager = createManager()                         ── [create-manager]
            │     └─ backendEnv() → userPaths() → mkdirSync(data/, logs/)
            ├─ ipcMain.handle(get-status / relaunch)             ── [register-ipc]
            ├─ await createWindow()                              ── [create-window]
            │     ├─ new BrowserWindow({ show:false })
            │     ├─ await loadFile(renderer/dist/index.html)    ── [load-renderer]
            │     └─ ready-to-show → win.show()                  ── [window-shown]
            ├─ initAutoUpdates()                                 ── [init-auto-updates]
            └─ healthy = await manager.start()                   ── [backend-start]
                  ├─ adopt running backend, or spawn mrp-backend.exe
                  ├─ poll GET /health until healthy or timeout
                  ├─ ok    → [backend-healthy] → writeStartupReport() → [ready]
                  └─ fail  → [backend-failed]  → Retry/Quit dialog
```

The bracketed names are the **startup stages** now emitted to the log and the
diagnostic report (see §5). The window is created **before** the backend is started
(it shows a "Backend Starting" loading screen), so *a backend failure cannot
explain a missing window* — by the time the backend is touched, the window already
exists. **A missing window means the process died at or before `create-window`.**

---

## 2. The eight required checks

| # | Stage | Executes? | Where |
|---|---|---|---|
| 1 | Electron executable launches | Yes — OS spawns the Electron binary | shortcut → `.exe` |
| 2 | Electron main process starts | Yes — `[module-init]` logs immediately | `main.ts` top-level |
| 3 | BrowserWindow creation executes | Yes — `[create-window]` before backend | `createWindow()` |
| 4 | Backend path resolution executes | Yes — `backendCommand()` in `createManager()` | `[create-manager]` |
| 5 | Backend process spawn executes | Yes — `manager.start()` → `spawnProcess()` | `[backend-start]` |
| 6 | Parent-watchdog init executes | Yes — `MRP_PARENT_PID` in `backendEnv()`; backend-side watchdog | `backendEnv()` |
| 7 | Health polling executes | Yes — `waitForHealth()` polls `GET /health` | `BackendManager` |
| 8 | Renderer load executes | Yes — `await loadFile(...)` | `[load-renderer]` |

All eight execute **in principle**. The bug is not a missing step; it is that a
failure in steps 1–4/8 was converted into a **silent process exit** with no window
and no report. The instrumentation proves which steps actually ran on a given
launch.

---

## 3. Failure conditions per stage

For each stage: **F** = overt failure, **S** = *silent* failure (no UI, no log,
no exit code the user sees), **P** = *packaged-build-only* (cannot reproduce in
`npm run dev`).

### `module-init`
- **F** — a throw at module top-level (bad import) aborts before `whenReady`.
- **S/P** — `import electronUpdater from "electron-updater"` resolving/initializing
  differently inside the asar/PyInstaller bundle. In dev the module is on disk.

### `single-instance-lock`
- **F (legitimate)** — lock already held → `app.quit()` and exit with no window.
  This is *correct* for a real second instance.
- **S** — a **previous instance still shutting down** keeps the lock. The lifecycle
  changes made shutdown *slower* (`will-quit` defers quit and waits up to 5 s + 2 s
  for the backend tree to die). If launch N is still tearing down when launch N+1
  starts, N+1 sees the lock held and **silently quits** — "no window, no process".
  Now logged as `single-instance-lock: another instance owns the lock — exiting`.

### `app-ready` / `free-port`
- **F/P** — `freePort()` binds `0.0.0.0`?, no — it binds loopback; a locked-down
  host firewall / EDR can still reject the bind, **rejecting the promise**.
- **S** — *this was the killer*: a `freePort()` rejection in the **un-guarded**
  `whenReady` chain hit the global `unhandledRejection` net → `process.exit(1)`,
  **before the window was ever created**. (See §4.)
- **P** — dev hard-codes `MRP_API_PORT` (no `freePort()` call), so this path only
  exists in the packaged build.

### `configure-env`
- **F** — trivial; assignments don't throw.

### `create-manager`
- **F/P** — `userPaths()` does `mkdirSync(userData/data)` & `mkdirSync(.../logs)`.
  Under a roaming/again-locked `%APPDATA%`, OneDrive contention or a read-only
  profile this **throws**. In dev these dirs already exist.
- **S** — same global-rejection swallow: the throw aborted startup silently.

### `register-ipc`
- **F** — `ipcMain.handle` throws only on a duplicate channel (not the case here).

### `create-window`
- **F** — `new BrowserWindow(...)` can throw if GPU/compositor init fails.
- **P** — packaged builds hit real GPU init; some VMs/RDP sessions fail here.

### `load-renderer`
- **F/P** — `await loadFile(renderer/dist/index.html)`: if the renderer bundle is
  missing/mispathed inside the asar, `loadFile` **rejects**.
- **S** — *second killer*: `new BrowserWindow` is created with `show:false`, so the
  window only becomes visible on `ready-to-show`, which **never fires if the load
  rejects**. The rejection then propagated to the global net → `process.exit(1)`:
  a window object existed but was never shown, then the process died → exactly
  "blue cursor, no window, no process."

### `window-shown`
- **S** — `ready-to-show` never firing (renderer hangs) leaves a permanently hidden
  window. Now backstopped by an 8 s "show anyway" timer.

### `backend-start` / health polling
- **F** — surfaced: the manager shows a **Retry / Quit** dialog (visible).
- **P** — spawning the frozen `mrp-backend.exe` (missing/AV-quarantined/blocked)
  only happens packaged; dev runs `python -m momentum.api`. This is **not** silent
  (dialog) and happens **after** the window is up, so it cannot cause "no window".

---

## 4. Root cause — could a lifecycle change terminate Electron before window creation?

**Yes.** Two changes from the lifecycle commits combine into the reported symptom:

1. **`Guarantee the backend sidecar never orphans on shutdown` (3eabee3)** added
   global crash nets:
   ```ts
   process.on("uncaughtException", (err) => { …; process.exit(1); });
   process.on("unhandledRejection", (reason) => { …; process.exit(1); });
   ```
   These were meant to force-kill the sidecar on a main-process crash. But they turn
   **any** unhandled rejection/throw into an immediate `process.exit(1)`.

2. The `app.whenReady().then(async () => { … })` startup chain had **no `.catch()`**,
   and the lifecycle work made that chain much heavier and entirely `await`-driven:
   `await freePort()`, `createManager()` (which does `mkdirSync`), and
   `await createWindow()` (which does `await loadFile`). **Any** of these rejecting
   — a blocked port bind, an unwritable `%APPDATA%`, a mispackaged renderer — becomes
   an unhandled rejection, which the new net escalates to `process.exit(1)`.

Because the window is created *inside* that chain and only shown on `ready-to-show`,
and because the **only** on-disk report (`writeStartupReport()`) ran *after*
`manager.start()` (later still), an early rejection produced:

- blue busy cursor (Electron started), then
- no window (died at/before `create-window`, or `loadFile` rejected pre-`show`),
- no process (`process.exit(1)`),
- **nothing on disk** (report never reached).

That is the reported failure precisely. The lifecycle changes didn't introduce the
*possibility* of an early throw — they introduced the **fatal, silent, evidence-free
escalation** of one. Pre-lifecycle, an unhandled rejection during startup was logged
by Electron but did **not** reliably kill the process, so the window often still
appeared.

---

## 5. The fix (instrumentation + de-silencing)

All in `desktop/electron/`; no architecture change.

**`startup-trace.ts` (new, pure, unit-tested)** — `StartupTrace` records each stage
with timestamps and monotonic deltas, the current stage, and a captured failure
(*which stage it died at*). Clock-injectable, no `electron` import — unit-tested in
`scripts/startup-trace.test.cjs`.

**`main.ts`**
- A module-level `trace` enters every stage (`module-init` … `ready`); each entry is
  logged as `[startup] → <stage> (+Nms, Mms in prev)` to the console **and** the
  rotating `mrp.log`.
- **The startup chain is guarded.** `startup()` runs inside `try`-equivalent
  `.then(() => startup().catch(fatalStartupError)).catch(fatalStartupError)`. A
  failure is now **traced, reported, surfaced (native error box if no window yet),
  and quit cleanly** — never a silent `process.exit`.
- `createWindow()` wraps `loadFile`/`loadURL`; a load failure **shows the window
  anyway** (so the app is visible) instead of rejecting into the fatal net, and an
  8 s backstop shows the window if `ready-to-show` never fires.
- `writeStartupReport()` now runs even when `manager` is null (early failure) and
  **always embeds the full `startup` timeline + any failure**, so a launch that dies
  before the backend still leaves a complete record on disk.
- The global `uncaughtException` / `unhandledRejection` nets now call
  `reportFatalCrash()` first (kill sidecar → record stage → flush report → native
  error box if no window), *then* exit — best-effort, never re-throwing.

**Result:** the failure can no longer be invisible. Either the window appears, or a
native error box names the failing stage, and in every case
`%APPDATA%/Momentum Lab/logs/startup-report.json` contains the stage timeline and
the captured cause.

### The startup diagnostic report on disk

`startup-report.json` (written after every start attempt, success or failure):

```jsonc
{
  "ts": "…", "appVersion": "…", "packaged": true, "platform": "win32",
  "host": "127.0.0.1", "port": 51234, "healthUrl": "http://127.0.0.1:51234/health",
  "databaseUrl": "sqlite:///…/Momentum Lab/data/momentum.db",
  "logDir": "…/Momentum Lab/logs",
  "backendReport": "…/Momentum Lab/logs/backend-startup.json",
  "startup": {                          // ← NEW: the main-process timeline
    "startedAt": "…", "finishedAt": "…", "durationMs": 263,
    "reachedWindow": true, "completed": true, "currentStage": "ready",
    "timeline": [ { "stage": "module-init", "sinceStartMs": 0, … }, … ],
    "failure": null                     // or { stage, message, stack } on failure
  },
  "backend": { … } | null               // null if it died before the manager existed
}
```

A verified packaged-mode boot log (headless, from this branch):

```
[startup] → module-init (+0ms, 0ms in prev)
[startup] → single-instance-lock (+2ms, 2ms in prev) acquired
[startup] → app-ready (+100ms, 98ms in prev)
[startup] → create-window (+101ms, 1ms in prev)
[startup] → load-renderer (+136ms, 35ms in prev) renderer/dist/index.html
[startup] → window-shown (+263ms, 127ms in prev)
```

---

## 6. How to diagnose a stuck install in the field

1. Open `%APPDATA%\Momentum Lab\logs\startup-report.json`.
   - `startup.failure` names the **stage** and **cause** (e.g. `free-port: bind
     EPERM`, `load-renderer: ENOENT …index.html`, `create-manager: EPERM mkdir`).
   - `startup.timeline` shows the **last stage reached** (the next stage is the
     suspect).
2. Cross-check `mrp.log` (`[startup] → …` lines) for the live sequence.
3. `backend-startup.json` covers backend-side failures (config/db) *after* spawn.
4. If `startup.json` is absent entirely, the crash predates `module-init` (a broken
   Electron/asar or OS-level block) — outside the main process.

---

## 7. Tests

- `desktop/scripts/startup-trace.test.cjs` — ordering/deltas, **failure names the
  stage**, idempotent `fail()`, `reachedWindow`, `done()` duration, non-Error
  throwables, greppable `summary()`. (Wired into `npm run test:backend`.)
- `desktop/scripts/smoke.cjs` — unchanged; the headless boot now emits the full
  stage timeline and still prints `MRP_SMOKE_OK`.
- `desktop/scripts/backend-manager.test.cjs` — unchanged, still green.
