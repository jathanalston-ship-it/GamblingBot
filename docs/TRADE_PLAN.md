# Trade Plan Generation

For any candidate, derive a complete, **read-only** trade plan — entry, stop,
three scale-out targets, reward:risk, expected holding period, suggested size and
portfolio risk — with explicit Risk / Reward / Failure summaries. **It never
places a trade.**

## What it produces

| Field | How it's derived |
|---|---|
| Entry | candidate price (breakout reference) |
| Stop | the **wider** of `stop_atr_mult × ATR` below entry and just below the nearest **swing-low support** (EMA fallback when no pivot) |
| Target 1/2/3 | R multiples of the entry→stop risk; **T1 snaps beneath the nearest swing resistance**; T2 lifted toward the analogs' avg winner, T3 toward their MFE |
| Reward/Risk | per-target R + a scale-out-weighted **blended** R |
| Expected Holding Period | analogs' avg winner hold, regime-adjusted (a low–high range) |
| Suggested Position Size | `risk_budget$ × regime_factor ÷ risk-per-share` (shares) |
| Suggested Portfolio Risk | resulting % of equity at risk |

## Methodology (inputs used)

- **ATR** — stop distance and volatility.
- **Support/Resistance** — **fractal swing pivots** from the scanner
  (`support_level` / `resistance_level`): the structural stop anchors to the
  nearest confirmed swing low, and T1 snaps just beneath the nearest swing high.
  EMAs are the fallback when no pivot exists; ATH proximity flags "blue-sky"
  (low-overhead) targets. Pivots are computed by `signals.indicators.swing_pivots`
  (a bar that is the extreme of `pivot_window` bars each side; the most recent
  `pivot_window` bars stay unconfirmed) and persisted on `scan_results`.
- **Historical Analogs** — same regime + sector cohort: expectancy, win rate, avg
  winner R (lifts T2), avg MFE (lifts T3), avg winner holding (sets the hold).
- **Volatility** — `ATR/price`; wide-vol names get a wider stop and smaller size.
- **Regime** — a size/aggression factor (bull 1.0 / neutral 0.7 / bear 0.4).

All tunable in `config/tradeplan.example.yaml`.

## Display (four sections)

- **Trade Plan** — entry, stop, T1/T2/T3 (price · R · gain · scale-out %), size,
  position value, portfolio risk.
- **Risk Summary** — risk per share + total, stop rationale (ATR / support),
  volatility.
- **Reward Summary** — per-target R + blended R, analog expectancy, blue-sky note.
- **Failure Conditions** — explicit invalidation: close below stop, relative
  volume fades, regime flips bearish, time stop at T1, loss of structural support.

## Components

- **Config** — `TradePlanConfig` (immutable Pydantic, validated).
- **Engine** — `momentum/tradeplan/engine.py`, a pure
  `TradePlanInputs -> TradePlan | None` (None when price/ATR are missing).
- **Service** — `api/tradeplan_service.py` assembles the inputs from the scan,
  conviction, regime, analog cohort and risk budget; **no persistence** (the plan
  is derived on demand).
- **API** — `GET /tradeplan/{symbol}` (404 when there's no scan price/ATR).
- **Desktop** — a **Trade Plan** view (left rail, and a "Plan" jump from the Scan
  inspector), keyed on the selected symbol, rendering the four sections above.
