# Desktop Application Audit — Momentum Lab

Audit of the Electron desktop app (`desktop/`) against the FastAPI backend.
Read-only assessment; no application code was changed. Findings are grounded in
the actual source (route definitions, view sources, the demo seeder).

---

## 1. Desktop readiness report

### Can the Electron frontend launch?

**Yes, on a prepared machine — but not verified in this environment, and the most
recent TypeScript has not been compiled.**

| Check | State |
|---|---|
| Electron main process (`electron/main.ts`) | ✅ Correct: free-port pick, single-instance lock, `userData` DB/log paths, prod loads `renderer/dist/index.html`, backend `/health` gate, error dialog on failure. |
| Vite entry (`renderer/index.html`) | ✅ Present (added previously — it was missing). |
| Component / hook imports | ✅ All resolve (AppShell, StageRail, Card, Page, Placeholder, hooks, all 14 components). |
| No hardcoded mock data in views | ✅ Every view reads the live API. |
| `node_modules` installed here | ❌ Absent — `npm install` + `npm run dev`/`build` must run on a dev machine. |
| Recent TS typechecked/built | ⚠️ **Not done.** The Updates view, the Electron menu and the preload `onNavigate` bridge were added without running `npm run typecheck` (no JS toolchain here). Run it before shipping. |

**Verdict:** launch path is architecturally sound and should work after
`cd desktop && npm install && npm run dev`, **pending** a `npm run typecheck`
pass on the newly added TypeScript.

### Can it communicate with the FastAPI backend?

**Yes — the mechanism is sound and the backend was verified working.**

- The renderer resolves the API base from the preload bridge
  (`window.mrp.apiBaseUrl` → `http://127.0.0.1:<port>`), falling back to a Vite
  env var, then the default loopback.
- The main process spawns the backend (dev: `python -m momentum.api`; packaged:
  `mrp-backend.exe`) and **waits for `/health`** before showing the window.
- Backend confirmed live: `GET /health` → 200; all read routers register; the
  new `/update/*` endpoints respond (200 / graceful degradation).
- CORS is permissive on a loopback-only listener; comms are HTTP over 127.0.0.1.

**Verdict:** communication works whenever the backend process is up (the main
process guarantees it before showing the UI).

---

## 2. Feature completeness report

8 view components, all live-API-backed; 3 routes are intentional placeholders.
**No screen fabricates data** — every screen shows whatever the database/API
returns, so "demo data" simply means the DB was seeded with `make seed-demo`.

| Screen (nav) | Route | Implemented? | Data source (endpoint) | Live? | Populated by demo seed? |
|---|---|---|---|---|---|
| **Scan** (1) | `/scan` | ✅ display | `GET /universe/scans` (+ `/conviction`) | Live | ✅ 15 ranked `scan_results` |
| **Candidates** (2) | `/candidates` | ✅ (reuses Scan) | `GET /universe/scans`, `/candidates/{sym}` | Live | ✅ 15 candidates |
| **Conviction** (3) | `/conviction` | ✅ display | `GET /conviction?symbol=` | Live | ✅ 15 `conviction_scores` (real engine) |
| **Analogs** (4) | `/analogs` | ✅ display | `GET /analogs?symbol=` | Live (computed from trades) | ✅ a candidate is now selectable |
| **Backtest** (5) | `/backtest` | ✅ display | `GET /backtests/optimizations` | Live | ✅ 14 `optimization_results` (2 studies) |
| **Replay** (6) | `/replay` | ✅ implemented | `GET /trades?status=closed`, `/conviction` | Live | ✅ 50 demo trades (select → detail + timeline) |
| **Paper** (7) | `/paper` | ❌ **Placeholder** | — | — | — |
| **Live** (8) | `/live` | ❌ **Placeholder** (gated) | — | — | — |
| **Portfolio** | `/portfolio` | ✅ display | `GET /portfolio/snapshots`, `/risk/metrics` | Live | ✅ equity curve (30 snapshots) + 3 `risk_metrics` windows |
| **Analytics** | `/analytics` | ✅ display | `GET /performance` (computed from trades) | Live | ✅ (50 demo trades → real metrics) |
| **Settings** | `/settings` | ✅ functional (read) | `GET /settings/config[/{name}]` | Live (reads `config/*.yaml`) | ✅ always (repo configs) |
| **Updates** | `/updates` | ✅ functional | `GET /update/status`, `POST /apply`, `/rollback` | Live | ✅ source install / degraded on packaged build |

### Key findings

- **Read-only app.** Every "action" is a display or a deliberate stub. The
  **"Run scan"** and **"Run backtest"** buttons are **disabled placeholders**
  (tooltip: "Planned: POST /scans/run …"); those POST endpoints **do not exist**
  (the only POSTs in the API are `/update/apply` and `/update/rollback`). This is
  by design (the read API "never accepts write payloads"), not a bug — but it
  means the desktop app cannot *trigger* scans/backtests; it only views results.
- **Demo seed gap — RESOLVED.** `make seed-demo` now also populates
  `scan_results` (15 ranked candidates), `conviction_scores` (15, via the real
  `ConvictionEngine`), `opportunity_classifications` (15 tiers), `risk_metrics`
  (3 windows) and `optimization_results` (14, 2 studies) — on top of the original
  `trades, signals, portfolio_snapshots, market_regimes, runs, audit_log`. **Every
  desktop screen now shows realistic data straight after the seed**, including the
  full Scan→Candidates→Conviction→Analogs research loop and the Backtest /
  Risk-metrics cards. See `docs/DEMO_DATA.md`.
- **Dashboard endpoint unused.** `GET /dashboard` exists but no view consumes it
  (the index route renders Scan, not a dashboard).
- **3 placeholder screens:** Replay, Paper, Live (Live is intentionally gated).

---

## 3. Screenshot checklist

Capture on a machine with `make seed-demo` applied (so trade-derived screens have
data), backend running, app launched. For the empty research screens, note the
empty-state rather than skipping.

- [ ] **App launch** — window opens, title "Momentum Lab", app icon in taskbar.
- [ ] **Scan** — layout + (empty state "0 candidates" under demo seed; populated
      only after a real scan).
- [ ] **Candidates** — list/inspector layout (empty under demo seed).
- [ ] **Conviction** — panel layout (empty under demo seed).
- [ ] **Analogs** — panel layout (needs a selected symbol).
- [ ] **Backtest** — "Optimization Results" card (empty under demo seed).
- [ ] **Replay** — placeholder card ("6 · Trade Replay").
- [ ] **Paper** — placeholder card ("7 · Paper Trading").
- [ ] **Live** — gated placeholder card ("8 · Live Execution 🔒").
- [ ] **Portfolio** — equity curve from 30 demo snapshots ✅; risk-metrics card empty.
- [ ] **Analytics** — performance metrics computed from 50 demo trades ✅.
- [ ] **Settings** — config file list + a selected YAML rendered ✅.
- [ ] **Updates** — installed vs latest version, Update/Roll-back buttons ✅.
- [ ] **Menu** — Help → "Check for Updates…" navigates to Updates.
- [ ] **Error state** — stop the backend, open a view → the `ErrorBox` shows.

> Tip: to screenshot the Scanner/Conviction loop with data, run a real scan
> (`mrp scan` once a data source is wired) or extend `seed_demo.py` to add
> `scan_results` + `conviction_scores`.

---

## 4. User acceptance test plan

Preconditions: backend reachable; DB migrated (`alembic upgrade head`); demo data
seeded (`make seed-demo`) unless a test says otherwise.

### UAT-A — Launch & connectivity
| # | Steps | Expected |
|---|---|---|
| A1 | Launch Momentum Lab | Window opens within ~10–30 s; no error dialog; title "Momentum Lab". |
| A2 | Observe first paint | The app shows a view (Scan) — i.e. the backend became healthy before the window appeared. |
| A3 | Quit the app | Process exits; `mrp-backend` is gone (Task Manager — no orphan). |
| A4 | Re-launch twice quickly | Single instance; the second launch focuses the first (single-instance lock). |
| A5 | Kill the backend, open any view | An `ErrorBox` ("Failed to load… Is the backend running?") — no crash. |

### UAT-B — Navigation
| # | Steps | Expected |
|---|---|---|
| B1 | Click every left-rail item | Each routes without error; active item highlights. |
| B2 | Open Replay / Paper / Live | Each shows its placeholder copy (Live shows the gated note). |
| B3 | Menu → Help → "Check for Updates…" | App navigates to the Updates screen. |

### UAT-C — Data screens (demo-seeded)
| # | Steps | Expected |
|---|---|---|
| C1 | Open **Analytics** | Expectancy / profit factor / win rate etc. computed from the 50 demo trades (non-empty). |
| C2 | Open **Portfolio** | Equity curve renders from 30 demo snapshots; risk-metrics card shows an empty state. |
| C3 | Open **Settings**, pick a file | The YAML content renders. |
| C4 | Open **Scan / Conviction / Backtest** | Each renders its layout with an **empty state** (demo seed doesn't populate these). |

### UAT-D — Updates (source install)
| # | Steps | Expected |
|---|---|---|
| D1 | Open **Updates** with no upstream change | "Up to date"; installed version shown; Update button disabled. |
| D2 | With an upstream commit available | "Update available — N change(s)"; Update button enabled. |
| D3 | Click **Update now** (clean tree) | Success message; advises restart. |
| D4 | Click **Roll back last update** | Success message; advises restart. |
| D5 | On a **packaged** build | Updates screen shows "in-app update not available — install a newer download". |

### UAT-E — Resilience
| # | Steps | Expected |
|---|---|---|
| E1 | Start app with port 8000 already in use | Still launches (a free port is chosen automatically). |
| E2 | First launch on a fresh machine | `%APPDATA%\Momentum Lab\data\momentum.db` is created; app works with empty screens. |
| E3 | External link (if any) clicked | Opens in the system browser, not inside the app. |

**Exit criteria:** UAT-A, UAT-B, UAT-C1–C3, UAT-D1, UAT-E all pass. UAT-C4 is an
*expected* empty state (documented gap, not a failure). UAT-D2–D5 require an
upstream change / packaged build to exercise fully.

---

## Recommendations (out of scope to implement here)

1. **Extend `seed_demo.py`** — ✅ **Done**: the seeder now adds `scan_results`,
   `conviction_scores`, `opportunity_classifications`, `risk_metrics` and
   `optimization_results`, so every screen demos with data. See `docs/DEMO_DATA.md`.
2. **Typecheck/build the desktop app in CI** — ✅ **Done**: `.github/workflows/desktop.yml`
   runs `npm install` → `npm run typecheck` (fails on any TS error) → `npm run
   build` → a headless Electron startup check on every push/PR. See
   `docs/DESKTOP_APP.md` § Continuous Integration.
3. **"Run" buttons** — ✅ **Done**: the app is now an operator console. Real
   action endpoints (`POST /actions/scan|backtest|paper-session|refresh-data|replay`)
   back the buttons, tracked as background jobs with progress + success/failure.
   See `docs/DESKTOP_APP.md` § Operator console.
4. **Replay screen** — ✅ **Done**: implemented as a trade inspector
   (`views/Replay.tsx`) — lists completed trades and shows entry/exit, holding
   period, MFE/MAE, regime, conviction, position size, exit reason and an SVG
   excursion timeline, reading `GET /trades?status=closed` + `GET /conviction`.
