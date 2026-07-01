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

## Trade Health — the battery percentage (never a black box)

Alongside thesis strength, every evaluation computes an explainable **0–100
Trade Health score** (`trade_lifecycle/health.py`) from eight weighted
components — Conviction, Trend, Volume, Volatility, Regime, Sector, **Time
decay** (thesis age vs a grace/full-decay window) and **Analog confidence**
(historical cohort expectancy, shrunk for small samples). Each component
reports the points it earned out of the points available, the delta versus a
neutral reading, and a detail string quoting the measured values (e.g.
`conviction 72/100, +2 since entry`) — the components sum exactly to the score,
proven by test. Weights + decay windows live in
`config/trade_lifecycle.example.yaml` (`health_weights`,
`time_decay_grace_days` / `time_decay_full_days`, `analog_min_sample`). The
health *band* (Strong/Stable/Weakening/Broken) and the trade's cached
`current_health_score` derive from this score; the full breakdown is persisted
per evaluation (`health_breakdown`, migration `0024`).

## Explainability engine

Every evaluation also persists a structured, **data-only** explanation
(`trade_lifecycle/explain.py`, stored in `trade_evaluations.explanation`):
**what changed** (price/conviction/health/action vs the previous evaluation,
with exact numbers), **why it changed** (the components that moved the score
most), **why confidence increased or decreased** (health delta + its largest
factor), **evidence for** and **evidence against** the recommendation (the
positive / negative health components with their measured details), and a
narrative capped at **250 words**. Everything is deterministic templating over
values the engine actually computed — no free text, no hallucination surface.

## Thesis journal

`GET /trade-lifecycle/{uid}/journal` turns the append-only history into the
trade's story: **Opened** (conviction/entry/stop) → one entry per evaluation
(the action when it isn't Hold; otherwise a measured label — *Thesis
strengthening / weakening*, *Momentum slowing*, *Still on thesis* — plus the
evaluation's narrative) → **Exited** (close reason + realized R). Derived on
demand from the immutable rows; nothing is ever replaced.

## Management analytics

`GET /trade-lifecycle/management-analytics` grades the **management logic
itself** — not win rate, not profit: average conviction decay, average trade
health, average holding period, maximum thesis age, the most successful health
decile (by realized R), best exits (loss avoided) and worst exits (upside left
behind, from the hindsight grades), average conviction recovery after dips,
average stop raises/lowers per trade, and average health before exit. Pure
helpers in `trade_lifecycle/management.py`; derived on demand.

## Desktop — Trades (Portfolio Command Center)

The **Trades** view is the daily screen: a card per tracked trade (symbol, the
health battery with color band, the current stance), click-through to the full
thesis. The detail panel includes a **Time Machine** — a slider over the
trade's evaluations showing health, action and the explanation at each point in
time (plus a clickable health-history strip) — the per-point **health
breakdown** table, the **explanation** panel (what changed / confidence /
evidence for & against), the **thesis journal** timeline, and the management
analytics grid.

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

## Realized outcomes grade the advice

A tracked trade records the *recommendation*; when it is actually executed, the
journal trade (`trades` table) records the *outcome* — and the two are linked
automatically (migration `0023`: `tracked_trades.journal_trade_id` FK +
`realized_r` / `realized_pnl` / `realized_at`).

- **Linking** (`link_journal_trades`, run at the end of every scan and by the
  manual reevaluate action): a recommendation is matched to the earliest
  unclaimed journal trade of the same symbol entered on/after the
  recommendation (24 h tolerance). One journal trade claims exactly one tracked
  trade; linking is idempotent.
- **Realization**: when the linked journal trade closes, its R multiple and net
  P&L are recorded on the tracked trade and the tracked trade is closed
  (`close_reason` = the journal exit reason).
- **Hindsight grading** (`trade_lifecycle/outcomes.py`, pure; derived on
  demand, no extra tables): for every evaluation of a realized trade, compare
  the R the trade was at when the advice was issued with the R it finally
  closed at. Defensive advice (Exit / Scale Out / Raise Stop) is **Correct**
  when the trade subsequently deteriorated and **Incorrect** when it kept
  climbing; constructive advice (Hold / Scale In / Lower Stop) is the mirror.
  Post-advice moves inside ±0.25R are **Unclear** and excluded from accuracy.
  The advice report aggregates per-action accuracy + average post-advice R, so
  the reevaluation engine itself is measurable — and its thresholds tunable —
  against realized results.

## API

- `GET /trade-lifecycle?status=&symbol=&limit=&offset=` — tracked trades,
  newest recommendation first.
- `GET /trade-lifecycle/summary` — counts by status / health / action.
- `GET /trade-lifecycle/advice-report` — hindsight accuracy of the advice
  (overall + per action + recent grades) over realized outcomes.
- `GET /trade-lifecycle/{trade_uid}` — one trade (original thesis + current
  state + realized outcome once linked & closed).
- `GET /trade-lifecycle/{trade_uid}/evaluations` — the full appended history.
- `GET /trade-lifecycle/{trade_uid}/grades` — that trade's advice graded
  against its realized outcome (empty until realized).
- `GET /trade-lifecycle/{trade_uid}/journal` — the thesis journal (the story).
- `GET /trade-lifecycle/management-analytics` — the management-quality metrics.
- `POST /actions/reevaluate-trades` — manual reevaluation job (pulls fresh
  bars, then links/realizes).

Scan results (`run_scan`) now report `tracked_trades_created`,
`trades_reevaluated`, `trades_auto_closed`, `trades_linked` and
`trades_realized`.

## Configuration

`config/trade_lifecycle.example.yaml` (user override:
`<MRP_USER_DIR>/config/trade_lifecycle.yaml`). All thresholds and component
weights are tunable; the config is frozen Pydantic with ordering validation and
a `config_hash` stamped semantics via `model_version`.

## Limits / follow-ups

- Advice grading uses the tracked trade's own entry/stop to compute the R at
  evaluation time and the journal's realized R for the outcome; execution
  slippage between the recommended and filled entry introduces a small,
  honest basis difference.
- `instrument` is `"shares"` today; wiring the options-eligibility verdict into
  creation would populate `"options"` recommendations.
- No desktop view yet — the API is complete, so a **Trades** screen (open
  theses, health chips, action badges, per-trade history sparkline) is UI work
  only.
