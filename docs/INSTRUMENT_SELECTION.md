# Instrument Selection Engine

> **Status: implemented.** Code in `src/momentum/instruments/`; persistence in
> the `instrument_selections` table (migration `0005`); config template
> `config/instruments.example.yaml`; tests in `tests/unit/instruments/`.

The strategy produces a **bullish thesis** (symbol, expected move, horizon). This
engine decides *how* to express it — **shares**, **long calls**, **vertical call
spreads** or **LEAPS** — from the thesis and the market/portfolio context. It
chooses the instrument and a suggested structure with an auditable rationale; it
does **not** size risk or route orders (those stay with `risk/` and
`execution/`).

## 1. Architecture

```
 signals/ (bullish thesis)                 data/ + risk/ + portfolio/ (context)
        │                                            │
        ▼                                            ▼
   TradeThesis ───────────────►  InstrumentSelectionEngine  ◄─── InstrumentContext
   (expected move, horizon,           │                          (RV, IV, liquidity,
    conviction)                       │                           risk budget, exposure)
                                      ▼
                 ┌────────────────────┴─────────────────────┐
                 │ 1. score 4 candidates (scoring.py)        │
                 │ 2. apply hard liquidity/availability gates│
                 │ 3. argmax → winner (+ tie-break priority) │
                 │ 4. build suggested structure (structures.py)
                 └────────────────────┬─────────────────────┘
                                      ▼
                            InstrumentDecision  ──►  instrument_selections (DB)
                            (instrument, structure, candidate scores, rationale)
```

Pure-functional scoring + hard gates + structure suggestion, composed by the
engine. The package depends only on `core` — it is self-contained and unit-tested
without the rest of the platform. Each candidate's suitability is a weighted
blend of bounded `[0,1]` sub-scores; gates (liquidity, listed options, LEAPS
availability) decide *eligibility*; the engine picks the highest-scoring eligible
instrument, falling back to **shares** when no option structure is eligible.

### Decision factors → instruments

| Factor | Shares | Long Call | Vertical Spread | LEAPS |
|---|---|---|---|---|
| **Expected move** | small ✓ | large ✓ | moderate ✓ | large ✓ |
| **Holding period** | long / indefinite ✓ | short–medium ✓ | medium ✓ | long ✓ |
| **Volatility (RV)** | — | sets premium scale | sets premium scale | — |
| **Implied vol (IV/RV)** | rich → ✓ | cheap → ✓ | **rich → ✓** (sell premium) | cheap → ✓ |
| **Liquidity** | share $-vol gate | OI + spread gate | OI + spread gate | + LEAPS-listed gate |
| **Risk budget** | ample → ✓ | small → ✓ (leverage) | small → ✓ | small → ✓ |
| **Portfolio exposure** | room → ✓ | — | scarce room → ✓ | — |

All four are *bullish* expressions; the engine trades off cost, leverage, theta
and capped vs open-ended payoff.

## 2. Database schema (`instrument_selections`, migration 0005)

One row per evaluated thesis — the auditable "why this instrument?".

| Column | Meaning |
|---|---|
| `run_id`, `signal_id` (unique FK), `symbol` | linkage |
| `instrument` | chosen: `shares` \| `long_call` \| `vertical_call_spread` \| `leaps` |
| `confidence`, `margin` | winning score and gap to runner-up |
| `iv_rv_ratio` | options richness at decision time |
| `expiry_days`, `long_strike`, `short_strike`, `target_delta` | suggested structure |
| `contracts`, `shares`, `est_cost`, `max_loss`, `max_profit` | sizing & defined-risk estimates |
| `rationale` (JSON), `candidates` (JSON) | full per-instrument scoring evidence |

`InstrumentSelectionRepository` provides `save_decision`, `for_run`,
`by_instrument` and `instrument_mix` (the selection distribution).

## 3. Implementation

```python
from momentum.instruments import (
    InstrumentSelectionEngine, TradeThesis, InstrumentContext,
)

thesis = TradeThesis(symbol="AAPL", entry_price=190.0,
                     expected_move_pct=0.35, holding_period_days=120)
context = InstrumentContext(
    realized_vol_annual=0.30, implied_vol_annual=0.24,   # cheap options
    risk_budget=750.0,                                   # 1R from the risk engine
    share_dollar_volume=2.0e9,
    has_options=True, options_open_interest=8000, options_spread_pct=0.02,
    leaps_available=True, available_exposure_pct=0.6,
)

decision = InstrumentSelectionEngine().select(thesis, context)
decision.instrument          # InstrumentType.LONG_CALL
decision.structure           # expiry, strike, target delta, contracts, max loss
decision.rationale           # human-readable explanation
decision.candidates          # all four scores + component breakdown
decision.to_record(run_id="live")   # -> instrument_selections row
```

Option premiums use the ATM approximation `0.4·S·σ·√T` (adjusted for moneyness)
for cost/defined-risk sanity — real quotes replace these at execution.

Configuration (`InstrumentSelectionConfig`) is immutable Pydantic with per-factor
weights and band thresholds, loadable from `config/instruments.yaml` and hashable
for reproducibility.

## 4. Tests

- **Scoring** — ramps and each scorer favoured under the right conditions.
- **Engine** — the canonical scenarios resolve to the expected instrument:
  illiquid/no options → **shares**; long hold + big move + cheap IV → **LEAPS**;
  big move + short hold + small budget → **long call**; rich IV + moderate move
  → **vertical spread**; rich IV + long hold + ample budget → **shares**.
- **Config** — defaults, YAML load, validation, hash.
- **Persistence** — round-trip, `instrument_mix`, schema columns.
