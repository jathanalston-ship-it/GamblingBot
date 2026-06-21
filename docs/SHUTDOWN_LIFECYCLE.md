# Electron Shutdown Lifecycle — Audit & Fix

**Problem:** `mrp-backend` could remain running after the desktop app closed.

**Root cause:** the sidecar was only killed inside Electron's quit events. Those
events do **not** fire when Electron crashes, is force-killed, or the machine shuts
down — so the backend orphaned, kept holding the loopback port and locking the
install directory (which also caused the installer "cannot be closed" error).

## Audit — termination paths

| Trigger | Before | After |
|---|---|---|
| `window-all-closed` | `app.quit()` → fired `stopBackend()` (force only) | `app.quit()` → drives graceful shutdown |
| `before-quit` | force-killed immediately | sets `shuttingDown`, cancels crash-recovery (no kill yet) |
| `will-quit` | force-killed | **defers quit** (`preventDefault`) → graceful stop → wait → force after timeout → `app.exit(0)` |
| main-process **crash** (`uncaughtException`/`unhandledRejection`) | **not handled** → backend orphaned | handler force-kills the tree, then exits |
| `process.exit` | **not handled** | `process.on("exit")` → synchronous force-kill |
| POSIX signals (`SIGINT`/`SIGTERM`/`SIGHUP`) | **not handled** | force-kill + exit |
| **hard kill / system shutdown** (no events fire) | **orphaned** | **backend parent-watchdog** self-exits |

## Layered termination strategy

1. **Graceful** (`will-quit`): `taskkill /T` (Windows) or `SIGTERM` (POSIX) to the
   tree, then wait up to `SHUTDOWN_TIMEOUT_MS` (5 s) for the process to exit.
2. **Force after timeout**: `taskkill /T /F` / `SIGKILL` on the whole tree, wait 2 s.
3. **Clean children & workers**: always the **process tree** (`/T`), so the
   PyInstaller bootloader's child (the actual uvicorn process) is taken down too. The
   backend runs uvicorn single-process (no extra workers), so the tree is exactly
   `mrp-backend.exe` → its python child.
4. **Crash safety nets**: `process.on("exit" | "uncaughtException" |
   "unhandledRejection" | signals)` force-kill synchronously (`spawnSync`), since an
   exiting/crashing main process can't run async work.
5. **Orphan backstop — the guarantee**: the backend gets `MRP_PARENT_PID` and runs a
   daemon **parent watchdog** (`momentum/api/parent_watchdog.py`) that polls the
   launcher PID and `os._exit`s the moment it disappears. This covers the cases no
   Electron handler can — Electron being `SIGKILL`ed, the OS terminating it on
   shutdown, or any path that skips the quit events entirely. **The sidecar cannot
   outlive its launcher.**

## Quit sequence (after)

```
window-all-closed ─► app.quit()
   ├─ before-quit:  shuttingDown = true; cancel restart timer   (recovery off)
   └─ will-quit:    preventDefault()
                    gracefulStopBackend(5s):
                       taskkill /T  (SIGTERM)  ──► wait ≤5s for exit
                       still alive? ► taskkill /T /F (SIGKILL) ► wait ≤2s
                    .finally ► app.exit(0) ► process 'exit' ► sync force-kill (no-op)

main crash / signal ─► force-kill tree (sync) ─► exit
Electron SIGKILL / OS shutdown (no events) ─► backend watchdog notices the dead
   parent PID within ~2s and exits itself.
```

## Verification — no orphaned processes

- **Unit** (`tests/unit/api/test_parent_watchdog.py`): `pid_alive` truth table;
  `watch_parent` fires `on_dead` exactly when the parent disappears; the watchdog is
  disabled without `MRP_PARENT_PID`.
- **End-to-end orphan test** (`test_no_orphan_when_parent_dies`): spawns a dummy
  parent, spawns a child process running the watchdog against that parent's PID,
  kills the parent, and asserts the **child exits on its own within seconds** — i.e.
  it does not orphan. This is the executable proof of the contract.

Electron `taskkill`/signal paths are validated by `npm run typecheck` + build and the
headless startup smoke test; the watchdog backstop is what makes the guarantee
testable in CI without a real desktop session.
