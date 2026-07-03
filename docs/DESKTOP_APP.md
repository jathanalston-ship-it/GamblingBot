# Desktop Application — Architecture, Structure & Plan

> **Status: scaffolded & building.** The Electron shell, the React/TS/Tailwind
> renderer (8 views, typed API client) and the FastAPI sidecar additions
> (dashboard + settings + CORS + `python -m momentum.api`) are committed under
> `desktop/` and `src/momentum/api/`. The renderer builds (`vite build`) and
> everything typechecks. This document is the architecture, the full folder
> structure, and the implementation plan to finish it.

> **UX redesign:** the renderer's *screens* are being reorganized from eight
> generic dashboards into a research→execution **workflow** (power-user, dense,
> keyboard-first). See [`DESKTOP_UX.md`](DESKTOP_UX.md) for the user flows and
> wireframes that drive the renderer implementation. The process/architecture
> below (Electron + FastAPI sidecar + SQLite) is unchanged.

Convert the Momentum Research Platform (a Python research backend) into a
**desktop-first** application: a single installable app that runs the whole
platform locally, with a rich UI over the existing engines and SQLite database.

## 1. Stack

| Layer | Technology | Notes |
|---|---|---|
| Desktop shell | **Electron** | window, lifecycle, spawns + supervises the backend |
| Frontend | **React + TypeScript + Tailwind** (Vite) | the renderer process; 8 feature views |
| Backend | **FastAPI + Python** (uvicorn) | the *existing* `momentum` package, exposed as a local HTTP API |
| Database | **SQLite** (SQLAlchemy + Alembic) | the existing research DB; a file in the user's data dir |

Nothing about the core platform changes — the desktop app is a **shell + UI over
the existing backend**. The strategy/risk/analytics engines are reused verbatim
through the API.

### Design system (2026-07 visual revamp)

One dark trading-terminal system, defined entirely in
`desktop/renderer/tailwind.config.ts` (semantic tokens — `surface-*`, `bull`,
`bear`, `accent`, `chart-*`) and `src/index.css` (font stack, tabular numerals,
thin scrollbars, focus rings, and the shared button voices `.btn-primary` /
`.btn-ghost` / `.btn-quiet` / `.btn-danger`, plus `.field` and `.overline`).
Chart **marks** use a CVD-validated palette (`chart.up #059669` / `chart.down
#ef4444` / `chart.line #3b82f6` / `chart.warn #d97706` — six-checks validator,
dark surface); **text** wears brighter text-grade tones (`bull #34d399`, `bear
#f87171`). Navigation is a grouped icon sidebar (`StageRail.tsx`: Today /
Research / Performance / System + a dev section) instead of the old 23-item
flat list; the top bar (`ContextBar.tsx`) clusters brand → market context →
account → run scope → ⌘K → PAPER badge. Shared primitives (`Card`, `Stat`,
`PageTitle`, `Badge`, `DataTable`, `ActionButton`) carry the system so every
view inherits it; page canvases are normalized to `p-5`. The 1–8 stage keys and
`g`-prefixed shortcuts are unchanged.

## 2. Architecture

Three processes, one machine, loopback-only:

```
┌──────────────────────────── Electron app (one process tree) ───────────────────────────┐
│                                                                                          │
│   ┌─────────────────┐        spawn + supervise        ┌──────────────────────────────┐  │
│   │  Main process   │ ───────────────────────────────►│  FastAPI sidecar (uvicorn)   │  │
│   │  (electron/main)│                                  │  python -m momentum.api      │  │
│   │                 │      waits for /health           │  127.0.0.1:8000 (loopback)   │  │
│   │  - BrowserWindow│◄─────────────────────────────────│                              │  │
│   │  - app lifecycle│                                  │   momentum.* engines         │  │
│   └────────┬────────┘                                  │   (scanner, regime, risk,    │  │
│            │ loads                                      │    analytics, backtest, …)  │  │
│            ▼   preload bridge (contextIsolation)        │            │                 │  │
│   ┌─────────────────┐         HTTP (fetch)             │            ▼                 │  │
│   │ Renderer (React)│ ───────────────────────────────►│   SQLAlchemy repositories    │  │
│   │  8 feature views│◄─────────────────────────────────│            │                 │  │
│   │  typed client   │         JSON                     │            ▼                 │  │
│   └─────────────────┘                                  │     SQLite (momentum.db)     │  │
│                                                         └──────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

- **Main process** (`desktop/electron/main.ts`) spawns the FastAPI sidecar, waits
  for `/health`, creates the `BrowserWindow`, and kills the sidecar on quit.
- **Renderer** (`desktop/renderer`) is a normal React SPA. It talks to the backend
  only over `http://127.0.0.1:8000` using `fetch`; it has **no Node access**
  (`contextIsolation: true`, `nodeIntegration: false`). The preload script exposes
  a tiny typed `window.mrp` bridge (just the API base URL + app metadata).
- **Backend** is the existing FastAPI app (`momentum.api.app:create_app`), run as a
  private sidecar bound to loopback. In dev it's `python -m momentum.api`; in a
  packaged build it's a PyInstaller one-file binary.

### Why a local HTTP sidecar (not PyO3 / embedded)?

The backend is already a FastAPI service with a clean read API and a session
factory on `app.state`. Reusing it as a sidecar means **zero rewrite**, the same
code runs in dev/CI/packaged, and the API stays independently testable
(`tests/unit/api`). The cost — shipping a Python runtime — is handled by
PyInstaller at package time.

## 3. Features → backend module → endpoint

All eight features map onto existing engines/repositories. Endpoints marked ✚ are
the ones added in this change; the rest already existed.

| Feature (view) | Backend module | Endpoint(s) |
|---|---|---|
| **Dashboard** | aggregate of the below | ✚ `GET /dashboard` |
| **Scanner** | `universe/` (momentum scanner) → `scan_results` | `GET /universe/scans` |
| **Trade Journal** | `analytics/` trade intelligence → `trades` | `GET /trades` |
| **Market Regime** | `signals/regime.py` → `market_regimes` | `GET /regimes`, `GET /regimes/latest` |
| **Portfolio** | `risk/` + `portfolio_snapshots`, `risk_metrics` | `GET /portfolio/snapshots`, `GET /risk/metrics` |
| **Settings** | `config/*.yaml` (Pydantic configs) | ✚ `GET /settings/config`, `GET /settings/config/{name}` |
| **Backtesting** | `backtest/` → `optimization_results` | `GET /backtests/optimizations` |
| **Analytics** | `analytics/performance` + `trade_analysis` | `GET /performance` |
| **Replay** | closed `trades` + `conviction_scores` | `GET /trades?status=closed`, `GET /conviction?symbol=` |
| **Paper Trading** | `runs` + `trades` + `portfolio_snapshots` + `signals` + `audit_log` | `GET /runs/recent`, `GET /trades`, `GET /portfolio/snapshots`, `GET /signals`, ✚ `GET /audit`, `POST /actions/paper-session` |

The **Replay** view lists completed trades and, for the selected trade, shows
entry/exit, holding period, MFE/MAE, market regime, conviction, position size and
exit reason, plus an SVG **excursion timeline** (entry → MAE → MFE → exit on an
R-multiple axis). It reads the existing trade/conviction endpoints — no new
backend — and follows the workspace run/symbol selection.

The **Paper Trading** view (replaces the old placeholder) shows the live paper
account — equity, daily P&L, total P&L, portfolio heat — plus open/closed
positions, recent sessions (selectable → session details + "Open in Replay"),
recent signals and recent audit events. It can **Run paper session** and
**Refresh data** (auto-refreshing the views), filters all panels to the selected
session, and opens Replay directly from any trade row. Every panel has explicit
loading / error / empty states. Two small **read** endpoints were added in-pattern
(no schema change): `GET /runs/recent` (recent session runs from the `runs` table)
and `GET /audit` (recent audit events); `PortfolioSnapshotOut` gained `daily_pnl`.

The read API is intentionally side-effect free. **Command** endpoints (run a scan,
run a backtest, write settings) are added as a separate, explicitly-guarded router
in Phase 3 (see the plan) so reads and mutations stay cleanly separated.

## 4. Folder structure

```
GamblingBot/
├── src/momentum/                 # the backend (unchanged engines)
│   └── api/                       # FastAPI layer
│       ├── app.py                 #   app factory + CORS  (updated)
│       ├── __main__.py            #   `python -m momentum.api` sidecar  (new)
│       ├── dependencies.py
│       ├── schemas.py             #   + DashboardOut, ConfigFileOut  (updated)
│       ├── services.py            #   + dashboard_summary, config read  (updated)
│       └── routes/
│           ├── dashboard.py       #   (new)
│           ├── settings.py        #   (new)
│           └── … (health, universe, trades, regimes, portfolio, risk, backtests, performance)
│
├── desktop/                      # the desktop application (this change)
│   ├── package.json               # orchestrates dev / build / package (npm workspaces)
│   ├── electron-builder.yml       # installer config (dmg / nsis / AppImage)
│   ├── README.md
│   ├── electron/                  # Electron main process (the wrapper)
│   │   ├── main.ts                #   spawn backend, create window, supervise
│   │   ├── preload.ts             #   contextBridge → window.mrp
│   │   └── tsconfig.json
│   └── renderer/                  # React + TS + Tailwind (Vite)
│       ├── index.html
│       ├── vite.config.ts
│       ├── tailwind.config.ts · postcss.config.js
│       ├── tsconfig.json · tsconfig.node.json
│       ├── package.json
│       └── src/
│           ├── main.tsx · App.tsx · index.css · vite-env.d.ts
│           ├── api/               # client.ts (fetch), types.ts (API shapes)
│           ├── hooks/             # useApi.ts (fetch + loading/error)
│           ├── lib/               # format.ts (money/pct/date)
│           ├── components/        # Layout, Sidebar, Card, DataTable, Stat, Badge, Page
│           └── views/             # Dashboard, Scanner, TradeJournal, Regime,
│                                  #   Portfolio, Backtesting, Analytics, Settings
│
├── docs/DESKTOP_APP.md           # this document
└── … (existing platform)
```

## 5. Communication & data flow

1. Renderer view mounts → `useApi("/dashboard")` → `fetch("http://127.0.0.1:8000/dashboard")`.
2. FastAPI route → service → SQLAlchemy repository → SQLite → Pydantic schema → JSON.
3. The view renders the typed response (cards + `DataTable`).

The API base URL is resolved as `window.mrp?.apiBaseUrl` (packaged/dev Electron) →
`VITE_API_BASE` (browser dev) → `http://127.0.0.1:8000` (default), so the same
renderer runs inside Electron **and** in a plain browser tab against `make serve`.

## 6. Security

- Backend binds **`127.0.0.1` only** — never a network interface. It is a private
  sidecar, not a server.
- Renderer runs with `contextIsolation: true`, `nodeIntegration: false`,
  `sandbox` on; the only host capability is the typed `window.mrp` bridge.
- External links open in the OS browser (`setWindowOpenHandler` → `shell.openExternal`).
- CORS defaults permissive because the listener is loopback-only; lock it down with
  `MRP_CORS_ORIGINS` if desired. A production CSP restricts `connect-src` to the
  sidecar origin.
- The Settings reader is path-traversal-guarded (resolves under `config/` only).

## 7. Packaging & distribution

1. **Freeze the backend** to a one-file binary (no Python needed on the user's box):
   ```bash
   pyinstaller --onefile --name mrp-backend \
     --collect-all momentum --collect-all alembic \
     -p src src/momentum/api/__main__.py
   # → desktop/build/backend/mrp-backend
   ```
2. **Build the renderer**: `npm run build:renderer` → `renderer/dist`.
3. **Compile electron main**: `npm run build:electron` → `dist-electron`.
4. **Package**: `electron-builder` bundles the renderer, the electron main, and the
   frozen backend (`extraResources`) into a per-OS installer (`release/`).
5. At runtime the packaged `main.ts` spawns `resources/backend/mrp-backend` instead
   of `python -m momentum.api`; the SQLite DB lives under `app.getPath("userData")`.

## 8. Implementation plan

**Phase 0 — Foundations (✅ done in this change)**
- FastAPI sidecar entrypoint (`python -m momentum.api`), CORS, `/dashboard`, `/settings/config`.
- Electron shell that spawns + supervises the backend and loads the renderer.
- React/TS/Tailwind app shell: routing, sidebar, typed API client, `useApi` hook.
- All 8 views rendering live data from the API. Renderer builds; everything typechecks.

**Phase 1 — Read-only app, polished (1–2 wk)**
- Adopt **TanStack Query** for caching/refetch/stale state (replace the minimal `useApi`).
- Charts (equity curve, drawdown, regime timeline, momentum distribution) via Recharts.
- Filtering/sorting/pagination on the Scanner & Journal tables; trade detail drawer
  (MFE/MAE, attribution). Run-selector (the `runs` table) wired through every view.
- Loading skeletons, empty states, error toasts, a backend-down banner.

**Phase 2 — Packaging (3–5 d)**
- PyInstaller spec for the backend; `electron-builder` targets (dmg/nsis/AppImage).
- DB in `userData`; first-run `alembic upgrade head`; bundle config templates.
- CI job to build installers per-OS; smoke-test the packaged app boots + serves `/health`.

**Phase 3 — Actions / commands (1–2 wk)**
- A guarded command router (`POST`): `/scans/run`, `/backtests/run`, `/settings/config/{name}`
  (validated writes through the Pydantic configs), `/regime/refresh`.
- Long-running jobs (scan/backtest) run in a worker; progress streamed over
  **WebSocket** (or SSE) to a Jobs panel; results land in the existing tables.
- Settings becomes editable: form-generated from each config's JSON schema, validated
  server-side by the existing immutable configs, persisted with a `config_hash`.

**Phase 4 — Live/paper trading surface (later)**
- Wire `execution/` + broker adapters behind the command router; positions/orders
  views; the dynamic risk-budget + risk-gateway pipeline surfaced per candidate.
- Notifications (regime flips, circuit-breaker trips, home-run classifications).

## 9. Running it (dev)

```bash
make install                 # backend (Python) in the repo
cd desktop && npm install    # desktop deps
npm run dev                  # Vite (5173) + Electron; Electron spawns the backend
# …or run them independently:
make serve                   # backend at 127.0.0.1:8000
npm --workspace renderer run dev   # UI in a browser tab against the API
```

## Continuous Integration

`.github/workflows/desktop.yml` validates the desktop app on every push / PR
(and via manual dispatch). The job runs on `ubuntu-latest` and **fails on any
TypeScript error**:

1. **Install** — `npm install` (workspace root + `renderer`).
2. **Typecheck** — `npm run typecheck` (renderer `tsc --noEmit` + the Electron
   `tsc -p electron/tsconfig.json --noEmit`). Any TS error fails the build.
3. **Build** — `npm run build` (Vite renderer → `renderer/dist`, Electron main →
   `dist-electron`), then a check that the expected artifacts exist.
4. **Electron startup validation** — `xvfb-run -a npm run smoke` launches the
   *built* app headlessly in smoke mode (`MRP_SMOKE=1`): the main process creates
   the window from the built renderer **without** the backend, waits for the
   first paint, prints `MRP_SMOKE_OK` and exits 0. `desktop/scripts/smoke.cjs`
   asserts that sentinel + a clean exit (with a timeout), so a renderer or main
   process that won't boot fails CI.

Run the startup check locally (needs a display, or Xvfb on Linux):

```bash
cd desktop
npm install
npm run build
npm run smoke          # Linux headless: xvfb-run -a npm run smoke
```

The smoke mode is gated entirely behind `MRP_SMOKE=1` and has no effect on a
normal launch.

## Operator console (action endpoints)

The app is an **operator console**, not just a viewer: buttons trigger real
backend work via `POST /actions/*`, tracked as background **jobs** so the UI
shows progress and a success/failure result.

| Button | Where | Endpoint | What it does |
|---|---|---|---|
| **Load sample data** | Context bar | `POST /actions/seed-demo` | populate the demo dataset (`momentum.demo.seed_all`) so every screen has data; idempotent, safe to re-run |
| **Run scan** | Scan view | `POST /actions/scan` | pull data → run the momentum scanner → persist `scan_results` |
| **Run backtest** | Backtesting view | `POST /actions/backtest` | pull data → event-driven breakout backtest → **persist** an `optimization_results` row + return summary |
| **Paper session** | Context bar | `POST /actions/paper-session` | full daily session (scan → conviction → risk → paper orders → journal) → **persist** an equity `portfolio_snapshots` + basic `risk_metrics` row |
| **Refresh data** | Context bar | `POST /actions/refresh-data` | pull bars for the universe into the local cache |
| **Replay** | (action endpoint) | `POST /actions/replay` | reconstruct a stored run (run + trades + audit) — available API; the Replay view itself now reads trades/conviction directly |

The **Load sample data** button is the fastest path to a populated app on a fresh
(or offline) install: it calls the demo seeder and reloads the views. A paper
session now writes an end-of-session **equity snapshot + basic risk metric** (so
the Portfolio screen fills from live activity), and each backtest persists a
single-row study (so the Backtesting screen accumulates a run history). These are
persistence-only additions — **no schema change**.

Long-running actions return a job (HTTP 202); the UI polls `GET
/actions/jobs/{id}` (`progress` 0..1 + `message`, then `succeeded`/`failed` with
a `result`/`error`). The job runner, session factory and market-data provider are
injectable via `app.state`, so the whole flow is tested offline with a stub
provider and a synchronous runner. Backend: `api/jobs.py`, `api/actions.py`,
`api/routes/actions.py`. Frontend: `hooks/useAction.ts`, `components/ActionButton.tsx`.

## First-run experience, sizing, notifications & profiles (2026-07)

- **Onboarding tour** (`components/OnboardingTour.tsx`, mounted in the
  AppShell) — a six-step modal walkthrough (connect data → pick universe →
  run a scan → read the Command Center → take a managed paper trade) that
  shows once (localStorage `mrp:onboarding:done`) and can be relaunched from
  Settings → **Show getting-started tour** (a `mrp:tour:start` window event).
- **Take-size dialog** (`components/TradeActions.tsx`) — "Take paper trade"
  now opens an inline confirm step: shares prefilled from the plan's
  suggested size (fetched from `/tradeplan/{symbol}`), editable, with the
  dollar risk (`shares × (entry − stop)`) recomputed live; Confirm posts
  `{symbol, quantity}` to `/actions/take-trade`.
- **Notification preferences** (Settings → **Notifications**;
  `GET/PUT /settings/notifications`, persisted under `notifications:` in
  `settings.yaml`) — a global on/off switch, a severity floor
  (info/warning/critical) and per-kind mutes (trade_managed,
  conviction_change, regime_change, concentration).
  `hooks/useAlertNotifications.ts` fetches the prefs on every poll and
  filters before firing OS notifications.
- **Profiles** (Settings → **Profiles**; Electron-only) — fully isolated data
  roots (own database, logs, settings, API keys) under one install. The
  active profile is recorded in `<dataRoot>/profile.json`; non-default
  profiles live under `profiles/<name>/` (`profileDataRoot` in
  `electron/paths.ts`, unit-tested). Switching (or creating) a profile
  relaunches the app so the backend is respawned against the new root — state
  can never bleed between profiles. IPC: `mrp:profiles:get` /
  `mrp:profiles:switch` via the preload bridge (`window.mrp.profiles`).
- **Paper execution venue** (Settings → **Paper Execution Venue**) — pick the
  internal simulator or Alpaca paper trading (see `docs/PAPER_SLICE.md`
  § Execution venues).
- **Onedir backend** — the frozen backend now ships as a PyInstaller
  **onedir** bundle (`resources/backend/mrp-backend/` with `_internal/`),
  which starts faster than one-file (no per-launch temp extraction) and
  avoids AV heuristics; `backendCommand()` resolves both layouts.
