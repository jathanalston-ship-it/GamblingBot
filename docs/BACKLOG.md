# Backlog

Deferred / future work, parked here so sessions don't re-discover it. Move an
item into a subsystem doc when it becomes active.

*2026-07 sweep: every item implementable offline was built (mark-to-market,
OHLC charts, $ADV/ATR columns, breadth, scan signals + scan audit-logging, CLI
provider flag, options instrument at creation, orders/fills persistence, partial
scale-outs + trailing stops, backtest equity-curve/trade-list persistence + view,
Plotly tearsheet, demo tracked trades, single-instance lock grace-retry). What
remains below is blocked on external data/services or a platform decision.*

## Blocked on external data / services

- **Options pricing & IV** — instrument-selection structures use the ATM premium
  approximation (`0.4·S·σ·√T`) and the IV inputs are a *realized*-vol proxy
  persisted on `scan_results` (`implied_vol`/`iv_rank`). Needs a real
  options-chain provider; plug it into the same two columns and the
  engine/service/UI need no changes.
- **Live-chain validation** — feed the recommended contract through the
  contract-level options-qualification gate against real quotes (replace the
  approximate Brenner–Subrahmanyam pricing with chain mids/greeks). Same
  provider dependency as above.
- **Ex-div event flags** on candidates — needs a corporate-actions data
  source. (Earnings dates are live via Yahoo calendarEvents; a dedicated feed
  would improve coverage.)
- **VIX in the context bar** — needs a volatility-index feed; breadth and
  realized vol (RV) are shown today.

## Blocked on platform / decision

- **Stale remote branch** — `claude/admiring-feynman-n8rhuj` still exists on the
  remote; the managed git proxy returns 403 on ref deletes and the GitHub MCP
  has no delete-branch tool. Delete it from the GitHub UI. All its commits are
  contained in `claude/vigilant-wozniak-oueczq`.
- **Live broker adapter** — locked by design: the platform is paper-only until
  the research loop proves out. The `Broker` protocol + persisted orders/fills
  are the seam a live adapter plugs into. (The market daemon already provides
  the timed scan loop.)

## Decided — keep as is (not planned)

- **Out-of-band audit channel** (QA FINDING-2, low) — audit rows share the
  business transaction *by design*: the log records facts (what committed), not
  attempts. Revisit only if a rolled-back-attempt trail becomes a requirement.
- **Remaining architecture stubs** — `execution/{order_manager,live_broker}.py`
  and `portfolio/{allocator,rebalancer}.py` stay documented stubs until the
  live-broker decision above unlocks them.

## Roadmap — top usability/functionality steps (2026-07 assessment)

*All ten roadmap items were built in the 2026-07 execution pass:* intraday
prices for trade management during regular hours (`actions._intraday_last_prices`),
the Alpaca **paper** broker adapter (`execution/alpaca_broker.py` + Settings →
Paper Execution Venue), the first-run onboarding tour (`OnboardingTour.tsx`),
the take-size confirm dialog (shares + live risk $ in `TradeActions`),
walk-forward backtesting with IS/OOS folds + degradation
(`backtest/walk_forward.py`, `POST /actions/walk-forward`) and the SPY
buy-and-hold benchmark overlay on the equity curve, earnings awareness
(`GET /earnings/{symbol}`, chip on Trade Plan, optional take-block via
`block_take_days_before_earnings`), the sector-concentration guard
(`sector_concentration` + deduped `concentration` alerts), notification
preferences (Settings → Notifications; severity floor + per-kind mutes,
honored by `useAlertNotifications`), multi-profile support (isolated data
roots via `profiles/<name>`, Settings → Profiles, relaunch to switch) and the
PyInstaller **onedir** backend build (faster cold start; dual-layout exe
resolution in `main.ts`).

Remaining refinements (not blockers):

- **Intraday granularity** — management uses 1-minute last prices when the
  provider supports them; a configurable 5/15m aggregation could reduce calls.
- **Earnings source** — the earnings date comes from Yahoo's calendarEvents
  (best-effort); a dedicated corporate-actions feed would add ex-div dates.
- **Onedir on real Windows** — validated by the release pipeline's packaged
  launch gate; first Windows release after this change should watch the
  release-validation report.

## Conventions for this file

One line per item: what + where + why deferred. Keep it short; delete done items.
