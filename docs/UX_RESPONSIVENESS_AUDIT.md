# Desktop UX Responsiveness Audit — 2026-07-03

Objective: **the application must never appear frozen.** Both reported
freezes — "Restart & Install" and the fresh installer's "Finish → Launch" —
were reproduced in code review, root-caused, and replaced with an explicit
asynchronous state machine plus visible UI at every moment. All numbers in
this report are measured (real boots, real Chromium renders); nothing is
assumed.

## 1. Root causes of the two freezes

| # | Flow | Blocking/silent operation | Duration | Fix |
| --- | --- | --- | --- | --- |
| 1 | Restart & Install | `mrp:update:install` called `quitAndInstall()` directly; `will-quit` then waited for the backend tree teardown (graceful SIGTERM → 5 s timeout → force-kill → 2 s) **with no UI feedback** — the window sat inert up to ~7 s before closing | up to **7 s** | The install handler is now an async sequence that **stops the backend first, on-screen** (`stopping-backend` state streamed to the Update overlay), so `will-quit` has nothing left to wait for and the window narrates every step until the moment it closes |
| 2 | Restart & Install | While NSIS runs, the app is gone (expected) — but the **relaunch** can collide with the old instance's teardown: the single-instance lock retry loop waits up to 12 × 750 ms ≈ **9 s with no window at all** ("Windows appears frozen") | up to **9 s** | A frameless **lock splash** ("Momentum Lab is restarting… waiting for the previous instance") now appears on the first failed lock attempt and closes on acquisition — there is always a window |
| 3 | Fresh installer → Finish ☑ Launch | Same lock-retry collision (NSIS `runAfterFinish` launches while the installer/old copy finishes), plus the backend cold boot before content appears | see §3 | Lock splash (above) + the window is created **before** the backend starts (existing BackendGate loading screen) + the whole journey is measured |
| 4 | Both | No state was persisted across the quit → installer → relaunch boundary, so the post-install launch looked like a cold start with no explanation | — | The UpdateFlow **marker file** survives the restart; the relaunched app resumes the same flow and the overlay narrates `waiting-for-installer → starting-backend → loading workspace → opening dashboard → ready` |

### Synchronous-operation inventory (main process)

Every sync call audited; the survivors are all sub-millisecond file
touches or paths where sync is mandatory:

- `readFileSync`/`writeFileSync` — profile/startup-report/marker JSON files (< 1 KB each, measured < 1 ms; startup-stage timestamps around them prove it).
- `dialog.showMessageBoxSync` — the backend-failure prompt; a deliberate modal decision point, shown only after async retries failed.
- `forceKillSync` / `spawnSync taskkill` — **only** on `process.on("exit")` / crash paths, where the event loop is already gone and async is impossible.
- Everything else in the update/startup path (port scan, backend spawn, health polls, backend stop, lock retries, renderer load) was already or is now fully asynchronous.

## 2. The update state machine (`desktop/electron/update-flow.ts`)

Explicit states, each with a label, status text, expected duration,
optional determinate progress, per-state timing and log lines, streamed
over IPC (`mrp:update:flow`) to the renderer:

`checking-for-updates → downloading-update (determinate %) →
verifying-update → preparing-restart → stopping-backend →
waiting-for-shutdown → launching-installer → waiting-for-installer →
starting-backend → waiting-for-health → opening-desktop → ready`
(+ `failed` with the captured error).

- **Survives the restart**: serialized to `update-flow.json` before
  `quitAndInstall()`; the relaunched app resumes the same machine, so the
  final `update-report.json` covers the whole journey — including a
  **`slowOperations` list of every state over 250 ms**, slowest first.
- **Logging**: every transition logs to the main-process log and into the
  flow's own log (persisted in the report).
- Tests: `desktop/scripts/update-flow.test.cjs` (7) — transitions/labels,
  determinate progress, the >250 ms report, serialize/resume across a
  simulated 15 s installer, failure capture, the 5 s reassurance
  threshold, listener isolation.

## 3. Startup performance — measured

Backend (this machine, 3 cold + 3 warm boots of the real
`python -m momentum.api`, instrumented in `api/__main__.py` →
`backend-timings.json`):

| Stage | Fresh DB (median) | Warm (median) | Worst seen | Tier |
| --- | --- | --- | --- | --- |
| spawn → Python ready (interpreter + imports) | 1 435 ms | 1 403 ms | 3 123 ms (first-ever boot, cold OS cache) | **> 1 000 ms** |
| SQLite engine init | 7.1 ms | 7.4 ms | 11.7 ms | ok |
| schema reconcile (create/heal tables) | 71 ms | 16 ms | 75 ms | ok |
| FastAPI `create_app` | 1.2 ms | 1.2 ms | 1.3 ms | ok |
| **spawn → /health 200 (total)** | **1 621 ms** | **1 521 ms** | **4 074 ms** | **> 1 000 ms** |

Renderer (built bundle in real Chromium, 3 runs):

| Stage | Runs | Median | Worst | Tier |
| --- | --- | --- | --- | --- |
| navigation → DOMContentLoaded | 67 / 43 / 34 ms | 43 ms | 67 ms | ok |
| navigation → React hydrated | 67 / 43 / 34 ms | 43 ms | 67 ms | ok |

**Every stage over 250 ms**: exactly one — the Python interpreter +
import chain (~1.4 s steady-state, ~3.1 s on a cold OS file cache). It is
92 % of time-to-health. Everything else (SQLite, migrations/reconcile,
app build, renderer load, hydration) is double-digit milliseconds.

### Continuous measurement

- Every launch's Electron stage timeline (StartupTrace) + the backend's
  `backend-timings.json` + the renderer's `renderer-hydrated` /
  `first-api-response` marks are appended to a rolling
  `startup-history.json` (last 50 launches).
- `startup-metrics.ts` (pure, tested: `startup-metrics.test.cjs`, 6)
  computes per-stage **average / median / p95 / worst-case** and
  classifies each stage against the **100 / 250 / 500 / 1000 ms** tiers.
- **Settings → Diagnostics → Startup Performance** renders the latest
  launch as a color-coded waterfall plus the stats table
  (`StartupWaterfall.tsx`), fed by `mrp:perf:startup`.

### Optimization recommendations (from the measurements only)

1. **Python import chain (~1.4 s) is the only meaningful target.** The
   onedir freeze already avoids onefile extraction; the next win is
   deferring heavy imports (`pandas`/provider stacks) out of the
   `momentum.api` import path so `/health` can answer earlier. Expected
   gain: most of the ~1.4 s; everything else combined is < 100 ms.
2. **Do not optimize SQLite/migrations/renderer** — measured at 7–75 ms
   and 34–67 ms; effort spent there cannot save a perceptible amount.
3. The 3.1 s cold-cache first boot is an OS page-cache effect (one-time
   per install); the installer-finish splash + BackendGate already cover
   it visually.

## 4. Seamless update experience

Clicking **Restart & install**: the button flips to a spinner
("Restarting…") and every control disables **on the same click**; the
full-screen Update overlay (`UpdateOverlay.tsx`) fades in and narrates
each step with a spinner/progress bar, a step checklist (Please wait… →
Backend shutting down… → Installer launching… → Waiting for installer… →
Backend starting… → Loading workspace… → Opening dashboard…), elapsed
time, and "Safe to leave running". After **5 seconds** in any one state,
extra reassurance appears ("Still working… nothing is frozen"). A failed
flow shows a **recovery dialog** (Retry / Continue without updating) —
never a dead window. Screenshots (generated in real Chromium via
`desktop/scripts/ux-screenshots.cjs`):

- `docs/screenshots/update-installing.png`
- `docs/screenshots/update-reassurance.png` (the >5 s state)
- `docs/screenshots/update-ready.png`
- `docs/screenshots/update-recovery.png` (failure + recovery)

## 5. Verification

- `update-flow.test.cjs` (7) + `startup-metrics.test.cjs` (6) — pass.
- Renderer + electron typecheck and build — clean.
- The interaction sweep across every mutating button is in
  `docs/UX_INTERACTION_AUDIT.md`.

Not verifiable in this environment (documented, not assumed): the NSIS
installer's own progress window and the packaged end-to-end restart are
exercised by the release pipeline's packaged-launch validation on
Windows; this audit's state machine is what removes every app-side
freeze around them.
