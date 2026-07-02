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
- **Earnings / ex-div event flags** on candidates — needs a corporate-actions
  data source; $ADV and ATR columns are already live.
- **VIX in the context bar** — needs a volatility-index feed; breadth and
  realized vol (RV) are shown today.
- **Backtest OOS split / vs-benchmark** — the per-run equity curve + trade list
  are persisted and rendered; walk-forward OOS folds and a benchmark overlay
  need a benchmark-series ingestion decision.

## Blocked on platform / decision

- **Stale remote branch** — `claude/admiring-feynman-n8rhuj` still exists on the
  remote; the managed git proxy returns 403 on ref deletes and the GitHub MCP
  has no delete-branch tool. Delete it from the GitHub UI. All its commits are
  contained in `claude/vigilant-wozniak-oueczq`.
- **Live broker adapter** — locked by design: the platform is paper-only until
  the research loop proves out. The `Broker` protocol + persisted orders/fills
  are the seam a live adapter plugs into. (The market daemon already provides
  the timed scan loop.)
- **PyInstaller `onedir` build** — onefile spawns a bootloader child + extracts
  to temp on every launch (slower first paint, AV locks, the double-process
  that motivated `taskkill /T`). Switching to onedir needs iteration on a real
  Windows machine; revisit `desktop/build/backend.spec` +
  `electron-builder.yml` extraResources.

## Decided — keep as is (not planned)

- **Out-of-band audit channel** (QA FINDING-2, low) — audit rows share the
  business transaction *by design*: the log records facts (what committed), not
  attempts. Revisit only if a rolled-back-attempt trail becomes a requirement.
- **Remaining architecture stubs** — `execution/{order_manager,live_broker}.py`
  and `portfolio/{allocator,rebalancer}.py` stay documented stubs until the
  live-broker decision above unlocks them.

## Roadmap — top usability/functionality steps (2026-07 assessment)

Ranked; each is independently shippable. 1–2 are the highest-leverage.

1. **Intraday bars for management** — manage stops/targets on 5–15m bars during
   market hours instead of the daily bar's last print (needs an intraday
   provider call; the daemon cadence already supports it).
2. **Broker paper-API integration (Alpaca paper)** — replace the internal
   simulator with real paper fills/quotes; the `Broker` protocol + orders/fills
   tables are the seam.
3. **Onboarding + first-run tour** — guided "pick provider → pick universe →
   run first scan → take first trade" flow for non-technical users.
4. **Position-size override at take time** — Take dialog with shares/risk
   editing (today it takes the plan's suggested size or a URL param).
5. **Walk-forward backtesting + benchmark overlay** — OOS folds
   (`backtest/walk_forward.py` stub) and SPY-indexed equity comparison.
6. **Earnings/ex-div awareness** — corporate-actions feed; flag "earnings in
   N days" on plans and optionally block entries just before reports.
7. **Portfolio-level correlation guard in management** — the risk engine
   checks correlation at entry; management could also warn when open trades
   crowd one sector/theme.
8. **Alert center + notification preferences** — mute rules, severity
   thresholds, per-kind toggles; today notifications are all-or-nothing.
9. **Multi-account/profile support** — separate paper books (e.g. aggressive
   vs conservative configs) with per-book analytics.
10. **PyInstaller onedir build** — faster cold start + fewer AV issues on
    Windows (already backlogged; needs a Windows iteration).

## Conventions for this file

One line per item: what + where + why deferred. Keep it short; delete done items.
