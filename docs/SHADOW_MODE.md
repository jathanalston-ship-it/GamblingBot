# Shadow Trading Mode

Before the app is allowed to place even a single live order, it must prove
itself: shadow mode **generates** the orders the strategy would place and
**never submits them anywhere** — not to the paper journal, not to the
brokerage venue, and structurally never to a live broker (the shadow path
has no submission surface; `orders_submitted` in the report is zero by
construction, proven by tests that assert the journal and venue tables
stay empty).

## How it works

Opt-in (`settings.yaml → shadow.enabled`, default **off**;
`GET/PUT /shadow/settings`). While enabled, every fresh scan runs the
shadow step (after management/autopilot, `api/shadow_service.run_for_scan`):

1. **Manage the open shadow book** — freshest price (intraday print or
   daily close) per symbol: MFE/MAE tracked, protective stop first
   (raised/breakeven stop honoured), then the plan target, then a
   breakeven ratchet at +1R (`shadow/engine.manage_shadow_trade`, pure).
   A close records the **expected exit fill** and the expected P&L / R.
2. **Generate this cycle's entries** — the same selection as autopilot
   (conviction floor 70, per-cycle and book caps, plan-derived stop /
   target / size), each with an **expected entry fill** modeled by the
   venue's real `ExecutionSimulator` against the live bar's estimated
   quote: spread crossed (buys pay the ask), participation slippage —
   never a midpoint. The distance from the decision price is stored as
   `entry_slippage_bps`. One row per (run, symbol), enforced by a unique
   key.

Persistence: `shadow_trades` (migration `0029`) — entry/exit expected vs
reference prices, slippage bps, stop/target/raised stop, MFE/MAE,
evaluations, status.

## The proving window & report

`GET /shadow` grades a **60-consecutive-trading-day** window
(`ShadowConfig.window_trading_days`):

- **Execution accuracy** — entry/exit slippage estimates (p50/p95 bps),
  fills modeled;
- **PnL** — expected total, expectancy (R), win rate, profit factor,
  largest winner/loser;
- **Exits** — counts by reason (stop / target);
- **Missed opportunities** — candidates above the conviction floor vs
  orders generated (what the caps left on the table);
- **day counter** — trading days observed vs 60, `window_complete`.

An empty ledger reports `None`s, never invented numbers.
`GET /shadow/trades` serves the raw ledger.

## Desktop

- **Settings → Shadow Trading Mode** — the enable toggle (with a plain
  explanation of what will and will not happen).
- **System → Shadow Mode** — the proving-window screen: day N of 60
  progress bar, orders generated vs orders submitted (always zero),
  execution-accuracy and P&L stat grid, exits breakdown, missed
  opportunities, and the full shadow ledger table.
- **Command Center → automation strip** — both proving windows at a
  glance: Paper Certification (day N of 30 / CERTIFIED / failing) and the
  Shadow Window (day N of 60, or "off"), refreshed every 5 minutes.

## Tests

`tests/unit/shadow/test_shadow.py` (6): spread-crossing fills,
stop/target/breakeven management, report grading, honest empty report,
60-day window completion, frozen config.
`tests/unit/api/test_shadow_service.py` (4): disabled-by-default records
nothing; enabled generates orders while the journal + venue stay empty
(never submits); a gap closes shadow trades with expected exits/P&L/R and
never double-opens per run; report/ledger/toggle round-trip over HTTP.
