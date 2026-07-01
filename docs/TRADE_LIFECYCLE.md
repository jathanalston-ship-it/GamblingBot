# Trade Lifecycle Engine — tracked trades + thesis reevaluation

The trade lifecycle engine answers two questions the platform previously could
not: **what trades has the system recommended**, and **is each recommendation's
thesis still valid today?**

Two phases, both automatic:

1. **Trade lifecycle** — every trade recommendation (a scan's persisted trade
   plan) creates a persistent **tracked trade** carrying the full original
   thesis: entry / stop / targets, conviction score + explanation, regime,
   sector, and the baselines deltas are later measured from (ATR, sector RS,
   momentum, analog expectancy).
2. **Thesis reevaluation** — every market scan **reevaluates every OPEN tracked
   trade**. It does not rescan the symbol looking for a new setup; it regrades
   the *existing thesis* against fresh evidence and appends an immutable
   evaluation record with a recommended action.

## Design guarantees

- **Never overwrite history.** `trade_evaluations` is append-only: one new row
  per (trade, reevaluation); the repository's `delete` raises. The tracked
  trade's original thesis columns are never updated — only a small
  current-state cache (thesis strength, health, status, `last_evaluated_at`).
- **Idempotent creation.** A symbol with an OPEN tracked trade is never
  duplicated by a re-run; a closed symbol can be recommended again.
- **Thousands of trades.** Hot paths are indexed (`status+symbol` on trades,
  `trade_uid+evaluated_at` on evaluations); analog cohorts are cached per
  (sector, regime) within a reevaluation pass; proven at 1,500 trades in tests.
- **Stale data never grades a thesis.** A stale scan skips tracking entirely,
  exactly as it skips conviction.

## What each reevaluation computes

| Metric | Source |
| --- | --- |
| Current conviction | The scan's persisted score for the symbol; recomputed via the real `ConvictionEngine` when the symbol dropped out of the scan |
| Conviction delta | current − original (at recommendation) |
| Momentum trend | blended trailing return now vs `trend_lookback_bars` ago → Rising/Flat/Falling |
| Relative-strength trend | price/benchmark ratio now vs then |
| Volume trend | 5-bar vs 20-bar average volume |
| ATR expansion | ATR now / ATR at entry |
| Market regime change | regime at entry vs latest regime (worsened ⇒ penalty) |
| Sector change | sector RS now vs at entry |
| Analog similarity change | analog-cohort expectancy now vs at entry |
| Thesis stability | 1 − normalized mean swing of recent thesis strengths |

The metrics blend into a **0–100 thesis strength** (weights in
`config/trade_lifecycle.example.yaml`; missing inputs are neutral, mirroring
the conviction engine), a **health** grade (Strong / Stable / Weakening /
Broken), and one **action** from a deterministic, most-defensive-first cascade:

1. **Exit** — price breached the stop (also auto-closes the tracked trade,
   config-gated), thesis strength below the exit threshold, conviction
   collapsed, or the regime worsened under a weak thesis.
2. **Scale Out** — thesis weakening, or momentum + RS both falling.
3. **Lower Stop** — ATR expanded ≥ 1.75× with a still-stable thesis (give the
   trade room; disable with `allow_lower_stop: false`).
4. **Raise Stop** — unrealized gain ≥ 1R with a stable thesis (lock in).
5. **Scale In** — thesis strengthened: conviction up, momentum rising,
   strength ≥ 80.
6. **Hold** — otherwise.

Every evaluation stores its reasons in plain language.

## Architecture

```
src/momentum/trade_lifecycle/
  config.py      TradeLifecycleConfig (+ ThesisWeights) — immutable Pydantic
  types.py       TradeStatus/TradeHealth/TradeAction/Trend enums;
                 TradeSpec, MarketFeatures, EvaluationInputs, ThesisEvaluation
  features.py    features_from_bars — pure bars → features (reuses indicators)
  evaluation.py  pure grading: trends, strength, stability, health, action
  engine.py      ThesisReevaluationEngine — thin wiring of the pure functions
```

Persistence (migration `0022`): `tracked_trades` (one row per recommendation,
unique `trade_uid`) and `trade_evaluations` (append-only history), with
repositories `TrackedTradeRepository` / `TradeEvaluationRepository`.

Service (`api/trade_lifecycle_service.py`): `run_for_scan` is the scan hook —
`create_from_recommendations` (one tracked trade per trade plan) then
`reevaluate_open_trades` (grades every OPEN trade against the scan's own bars,
no second pull). `actions.reevaluate_trades` is the manual between-scans
trigger: it pulls bars for just the held symbols (+ SPY) and reevaluates.

## API

- `GET /trade-lifecycle?status=&symbol=&limit=&offset=` — tracked trades,
  newest recommendation first.
- `GET /trade-lifecycle/summary` — counts by status / health / action.
- `GET /trade-lifecycle/{trade_uid}` — one trade (original thesis + current state).
- `GET /trade-lifecycle/{trade_uid}/evaluations` — the full appended history.
- `POST /actions/reevaluate-trades` — manual reevaluation job (pulls fresh bars).

Scan results (`run_scan`) now report `tracked_trades_created`,
`trades_reevaluated` and `trades_auto_closed`.

## Configuration

`config/trade_lifecycle.example.yaml` (user override:
`<MRP_USER_DIR>/config/trade_lifecycle.yaml`). All thresholds and component
weights are tunable; the config is frozen Pydantic with ordering validation and
a `config_hash` stamped semantics via `model_version`.

## Limits / follow-ups

- The tracked trade records the *recommendation*; it is not connected to the
  paper-trading journal (`trades`). Linking a tracked trade to an executed
  journal trade (entry_signal-style) is a natural follow-up.
- `instrument` is `"shares"` today; wiring the options-eligibility verdict into
  creation would populate `"options"` recommendations.
- No desktop view yet — the API is complete, so a **Trades** screen (open
  theses, health chips, action badges, per-trade history sparkline) is UI work
  only.
