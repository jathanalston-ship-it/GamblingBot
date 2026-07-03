# Automation Mode, Long-Running Trading Mode & Resilience

Momentum Lab can run continuously for days while the automated paper trader
(Auto Pilot, `docs/AUTOPILOT.md`) is active. Three layers make that safe:

## 1. Automation Mode — the machine stays awake

While Auto Pilot is ON (and the *Prevent system sleep* setting is enabled —
default ON), the Electron shell holds a power-save blocker via Electron's
`powerSaveBlocker` API in **`prevent-app-suspension`** mode.

**What is prevented:**

- ✓ System sleep — the CPU, timers, networking, the scheduler and the
  backend keep running.

**What is NOT prevented (by design):**

- Display sleep — the screen may turn off.
- The screen saver.
- Manual user lock — locking the machine does not pause automation.

Lifecycle guarantees (`desktop/electron/automation.ts`, `AutomationManager`,
pure and injectable):

- **Auto Pilot starts → the blocker starts.** The shell polls
  `GET /settings/autopilot` every 60s and the renderer nudges it
  (`mrp:automation:sync`) immediately after every settings save. Status shows
  *Automation Mode Active — Sleep Prevented*.
- **Auto Pilot stops → the blocker is released.** So does turning the
  prevent-sleep checkbox off mid-run.
- **Repeated starts never leak** — the manager holds at most ONE blocker id,
  ever; re-syncs reuse it.
- **Unexpected exit → automatic release.** The blocker is released on
  `will-quit`, on the `process 'exit'` safety net and on the fatal-crash
  path (`reportFatalCrash`); if the process dies harder than any of those,
  the operating system itself drops the blocker with the process. **A
  blocker can never remain active after the application closes.**

Tests: `desktop/scripts/automation.test.cjs` (7 cases — start, stop,
25-start no-leak, crash cleanup, quit release + harmless double-release,
opt-out never blocks, mid-run opt-out releases).

## 2. Long-Running Trading Mode — the preflight

Turning Auto Pilot ON (`PUT /settings/autopilot` with `enabled=true`) first
grades seven subsystems (`api/automation_health_service.py`); **any critical
subsystem refuses the start (HTTP 409) and the response names every failing
subsystem and why** — Auto Pilot does not start on a broken foundation.

| Subsystem | How it is checked | Critical when |
| --- | --- | --- |
| Backend Running | this process answered | never (it answered) |
| Scheduler Running | the market daemon thread state | not running |
| Sleep Prevention | the prevent-sleep setting (the live blocker is the shell's; the UI merges it) | never (warning when disabled) |
| Internet Connected | a real 3s HTTPS probe of the provider's host | unreachable |
| Market Calendar Loaded | the ET schedule resolves the current state | calendar raises |
| Clock Synchronization | local UTC vs the probe's `Date` header | drift > 10 min (warning > 2 min) |
| Data Provider Reachable | the probe's HTTP status | unreachable or 5xx |

`GET /automation/health` serves the live grades continuously; the Command
Center's automation strip shows **Automation Health —
Healthy / Warning / Critical** with every subsystem expandable, plus
**Automation Status, Sleep Prevention, Backend Status, Last Scan, Next
Scan**. The network probe is injectable, so tests run offline.

## 3. Automation Resilience — surviving restarts

Automation state persists in `<MRP_USER_DIR>/automation_state.json`
(`api/automation_state.py`):

- the daemon **heartbeats** every loop iteration (scan or idle) with the
  freshest scan time and cadence;
- a deliberate stop **marks a clean shutdown** (the FastAPI shutdown hook),
  so a normal quit is never reported as a crash;
- on startup, `detect_recovery` compares the last heartbeat with now: an
  unclean gap ≥ 30 minutes records **downtime** and **missed scans** —
  counted minute-by-minute against the real ET schedule
  (`missed_scans_between`), so a weekend outage honestly reports zero.

Because Auto Pilot lives in `settings.yaml`, open paper positions live in
the `trades` table, and the daemon autostarts with the app, **everything
resumes by construction** once the app is running again: the scheduler, the
scan loop, open-position management, and Auto Pilot entries. On Windows,
the packaged app additionally registers itself as a **login item while Auto
Pilot is ON** (`app.setLoginItemSettings`), so an unexpected OS restart
resumes automation as soon as the user signs back in (removed when Auto
Pilot is turned off; skipped for portable builds).

The Command Center shows the banner:

> **Recovered After Restart** — Recovered successfully — down 42 min,
> missed 14 scans. Resuming…

`GET /automation/recovery` (+ `GET /automation/state` for raw diagnostics).

Tests: `tests/unit/api/test_automation.py` (11 cases — heartbeat/clean-mark
persistence, first-run and clean-stop are not recoveries, fast restart is
not a crash, mid-session gap records ~120 missed scans and never re-reports,
weekend outage misses zero, pure missed-scan math, all-healthy grading,
offline = critical + preflight block, clock-drift grades, paused-daemon
warning, and the full PUT-refused-then-accepted gate over HTTP).
