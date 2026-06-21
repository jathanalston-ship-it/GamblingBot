# Electron Backend Startup — Reliability Audit

The desktop app runs the FastAPI backend as a private loopback **sidecar**
(`mrp-backend.exe` in prod, `python -m momentum.api` in dev). This audits whether
that startup is *guaranteed*, and documents the reliability fixes in
`desktop/electron/main.ts`. No architecture change — same sidecar model, hardened.

## Audit answers

| # | Question | Before | After |
|---|---|---|---|
| 1 | Spawns `mrp-backend` automatically? | **Yes** — `startBackend()` in `app.whenReady()` | Yes |
| 2 | Verifies startup before rendering? | **Yes** — `await waitForBackend()` blocks `createWindow()` | Yes |
| 3 | Verifies `/health`? | **Yes** — polls `GET /health` every 300 ms | Yes |
| 4 | Retries if startup fails? | **Partial** — re-polled `/health` for 60 s, but never re-spawned a crashed process and didn't fail-fast on exit | **Yes** — bounded spawn retries + fail-fast + post-window crash recovery |
| 5 | Surfaces startup errors? | **Partial** — generic dialog then quit; the actual cause (stdout/stderr) was thrown away (`stdio:"inherit"`); no Retry | **Yes** — captures backend output, shows the real cause, offers **Retry/Quit** |

## Failure points identified (and the fix)

| Failure point | Symptom | Fix |
|---|---|---|
| `spawn()` `'error'` not handled (missing/broken binary) | unhandled error, opaque | `backend.on("error", …)` records it and marks `backendExited` |
| No fail-fast when the process exits during the wait | a crashing backend made the user wait the full 60 s | `waitForBackend` throws immediately when `backendExited` |
| No process re-spawn on a failed start | one transient failure → dead app | `bringUpBackend()` retries spawn+verify (`MAX_START_ATTEMPTS`) |
| No recovery if the backend dies **after** the window is shown | every screen 500s / "is the backend running?" forever | `exit` event → `scheduleBackendRestart()` (bounded, reloads window on success) |
| Cause discarded (`stdio:"inherit"`) | dialog couldn't say *why* | `stdio:["ignore","pipe","pipe"]` → ring buffer → shown in the dialog + log path |
| Dialog only "Quit" | no way to recover without reinstalling | `dialog.showMessageBoxSync` with **Retry / Quit** |

## Startup sequence (after)

```
app.whenReady()
   │
   ├─ pick free loopback port; export MRP_API_PORT / DB / log dir
   │
   ├─ bringUpBackend()  ── attempt 1..MAX_START_ATTEMPTS ──┐
   │     ├─ startBackend()  (spawn; capture stdout/stderr; on error/exit → backendExited)
   │     └─ waitForBackend()  poll GET /health every 300ms
   │            ├─ 200 OK ............................. return TRUE ─────────────┐
   │            ├─ backendExited .... throw (fail fast) → stopBackend → retry    │
   │            └─ timeout ........... throw → stopBackend → retry               │
   │                                                                            │
   ├─ if all attempts fail → dialog [Retry / Quit] ── Retry ─► bringUpBackend() ─┘
   │                                              └─ Quit ─► app.quit()
   │
   ├─ createWindow()  (loads built renderer)  ◄── only reached once /health is OK
   ├─ recoveryEnabled = true
   └─ initAutoUpdates()

runtime:  backend 'exit' (crash, recoveryEnabled, not shutting down)
   └─ scheduleBackendRestart()  (≤ MAX_RUNTIME_RESTARTS)
         ├─ startBackend() + waitForBackend()
         │      ├─ OK → window.reload()  (stale errors clear)
         │      └─ fail → stopBackend() → exit event → reschedule (bounded)
         └─ exceeded cap → dialog [Retry / Quit]

shutdown (before/will/quit):  shuttingDown = true; clear restart timer;
   stopBackend() kills the whole process TREE (taskkill /T) so it can't orphan.
```

## Guarantees now

- The window is **never** shown until `/health` returns 200.
- A failed start is **retried**, then surfaced with the **real cause** and a **Retry** option — never a silent blank/500 window.
- A backend that dies mid-session is **automatically re-spawned** (bounded) and the
  window reloads; persistent failure escalates to the Retry/Quit dialog.
- Crash recovery is disabled during intentional shutdown, and the sidecar is always
  torn down as a tree (no orphan holding the port / blocking the next installer).
