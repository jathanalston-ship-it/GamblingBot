# User Workflow Audit — Momentum Lab desktop

Traces every action a user expects to perform, **starting from a fresh install
with no demo seed**, through the desktop view → API endpoint → backend module →
database. Grounded in the actual source (`api/actions.py`, `orchestration/engine.py`,
the view sources, and a live run against an empty DB).

## Fresh-install baseline (verified)

- The Electron app spawns `mrp-backend` (`python -m momentum.api`), which calls
  `create_all()` on startup, so **the SQLite schema exists on first launch**.
- Every read endpoint returns **200 + empty** on an empty DB (no 500s);
  `/regimes/latest` returns 404 (rendered as "no regime"). So the app **launches
  and every screen shows a clean empty state**.
- All five command actions (`refresh-data`, `scan`, `backtest`, `paper-session`,
  `replay`) use a **keyless `YahooProvider`** by default → **they require internet**.
  Offline, scan/backtest/paper fail with `no market data available for the universe`.

## Status update (P0 + P1 implemented)

The shortest-path items below are now **done**:

- **P0 — "Load Sample Data" button** (context bar → `POST /actions/seed-demo`):
  one click seeds the full demo dataset (idempotent), then reloads every view.
  Fastest path to a populated app, including offline. Seeder logic moved to the
  importable `momentum.demo.seed_all` so it ships in the desktop build.
- **P1 — paper session persists `portfolio_snapshots` + `risk_metrics`**: the
  orchestration engine writes an end-of-session equity snapshot and a basic risk
  metric, so **Portfolio now populates from live activity**.
- **P1 — backtest persists `optimization_results`**: each run is saved as a
  single-row study, so **Backtesting now shows a live run history**.

No schema changes were needed. The remaining gaps (live `conviction_scores`,
`market_regimes`, the Paper screen) stay as documented future work.

## The core finding (pre-P1, for reference)

The live pipeline persisted **`runs`, `trades`, `audit_log`** (and `scan_results`
via *Run Scan*). It did **not** persist `portfolio_snapshots`, `risk_metrics`,
`conviction_scores`, `opportunity_classifications`, `optimization_results`, or
`market_regimes` — outside the demo seeder. P1 closes the
`portfolio_snapshots` / `risk_metrics` / `optimization_results` gaps;
`conviction_scores` and `market_regimes` remain demo-only for now.

| # writers (live app, excl. demo seed & tests) | table |
|---|---|
| ✅ written live | `runs`, `trades`, `audit_log`, `scan_results` (Run Scan only) |
| ❌ never written live | `portfolio_snapshots`, `risk_metrics`, `conviction_scores`, `opportunity_classifications`, `optimization_results`, `market_regimes` |

---

## Audit table — the six focus areas (prioritized by user impact)

| Action (focus area) | Status | What works | What's broken / missing |
|---|---|---|---|
| **Paper Trading** | 🟡 Partially Works | "Paper session" (context bar) runs the real orchestration: scan → conviction → risk → paper order → journal; persists `runs`+`trades`+`audit`, **and now an equity snapshot + risk metric (P1)**. Unblocks Replay/Analytics/Portfolio. | The dedicated **Paper screen (`/paper`) is still a Placeholder** — no open-position monitor. `conviction_scores` not persisted. Needs internet. |
| **Portfolio Management** | 🟢 Works (P1) | Equity snapshot + basic risk metric are **written at the end of every paper session**; the Portfolio screen now fills from live activity (and the columns were fixed to real fields). | Risk metric is intentionally basic (per-session inception window); no multi-window risk analytics live yet. |
| **Backtesting** | 🟢 Works (P1) | "Run backtest" runs a real event-driven breakout backtest **and persists an `optimization_results` row**; the screen accumulates a run history (study + objective). | Single fixed breakout strategy; no params/objective UI; `parameters` column not surfaced. Needs internet. |
| **Scanning** | 🟢 Works (needs internet) | "Run scan" pulls data, ranks the universe, persists `scan_results`, and the Scan/Candidates screen shows ranked candidates with an empty→populated transition. | Doesn't create a `runs` row, so the scan **isn't in the run selector** (works only because a null run shows the latest scan). Conviction is **not** computed/persisted, so the Scan→**Conviction** step is dead in the live flow. |
| **Replay** | 🟢 Works | Lists completed trades; selecting one shows entry/exit, holding period, MFE/MAE, regime, conviction, position size, exit reason + an excursion timeline. Reads `trades`+`conviction`. | Conviction shows "—" in the live flow (conviction never persisted); timeline MFE/MAE ordering is illustrative. Needs trades (paper session or demo). |
| **Analytics** | 🟢 Works | Expectancy / profit factor / payoff / trend-capture computed **live from `trades`** via `/performance`. The positive-skew metrics are real. | Empty until at least one paper session (or demo) produces trades. The equity-curve "performance" block needs snapshots (see Portfolio). |

### Supporting screens (context for the loop)

| Screen | Status | Note |
|---|---|---|
| **Conviction** | 🔴 Missing (live) | No live writer for `conviction_scores`; only demo. Breaks the Scan→Conviction→Analogs loop. |
| **Market Regime** + context-bar regime | 🔴 Missing (live) | No live writer for `market_regimes`; regime badge stays "no regime". |
| **Analogs** | 🟢 Works | Computed from `trades`; needs trades + a selected symbol. |
| **Settings** | 🟢 Works | Reads `config/*.yaml`. |
| **Updates** | 🟢 Works | Source install: real self-update; packaged build: degrades to "install a newer download". |

Legend — 🟢 Works · 🟡 Partially Works · ⚪ Placeholder · 🔴 Missing.

---

## Shortest path to a usable desktop application

Ordered by **impact ÷ effort**. P0–P2 turn the live pipeline from "fills 3 of 6
screens" into "fills all six". None require schema changes (the tables already
exist) — they are **persistence-wiring** tasks.

| Pri | Change | Unblocks | Effort |
|---|---|---|---|
| **P0 ✅** | **First-run "Load sample data" button** (`POST /actions/seed-demo` → `momentum.demo.seed_all`). | Instantly makes **every** screen explorable on a fresh, **offline** install — the fastest possible "usable" perception. | S |
| **P1 ✅** | Write a `PortfolioSnapshot` (+ a basic `RiskMetric`) at the end of `engine.run_day`. | **Portfolio Management** live (equity curve + risk) — the headline screen. | S–M |
| **P1 ✅** | Persist the `run_backtest` summary as an `OptimizationResult` row (single-row study). | **Backtesting** table live after a run. | S |
| **P2** | Persist `conviction_scores` (and the paper session's `scan_results`) during the paper/scan path. | **Conviction** + the Scan→Conviction→Analogs loop + Replay's conviction field. | M |
| **P2** | Persist one `market_regime` per session (regime is already computed for sizing). | **Market Regime** screen + the context-bar regime badge. | S |
| **P3** | Build the **Paper screen** (`/paper`): open positions, last-session report, "Run session" CTA. | Turns Paper Trading from "a button in the bar" into a real screen. | M |
| **P3** | `run_scan` creates a `runs` row (or unify the scan/paper run-id scheme). | Scans appear in the run selector; run-scoped views line up. | S |
| **P4** | Graceful **offline / no-data** UX: friendly banner + the P0 "Load sample data" CTA when a command action returns `no market data`. | Robust first-run on machines without internet. | S |

**Bottom line:** the app **launches clean and three screens already work live**
(Scanning, Replay, Analytics). The single highest-leverage move for a *demoable*
app today is **P0** (a UI button to seed the sample dataset). The shortest path to
a *genuinely live* app is **P1×2** — persist a snapshot/risk row per session and
persist the backtest result — after which a user can refresh data → scan → paper
session → and see Portfolio, Analytics, Replay and Backtesting all populated from
their own activity.
