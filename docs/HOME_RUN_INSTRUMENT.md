# Home-Run Instrument Selector

> **Status: implemented.** Code in `src/momentum/instruments/home_run_selector.py`
> and `home_run_config.py`; config template
> `config/home_run_instrument.example.yaml`; tests in
> `tests/unit/instruments/test_home_run_selector.py` /
> `test_home_run_config.py`.

Given a **qualified Home-Run trade**, this engine chooses the *optimal way to
express it*. It scores five expressions and returns the best fit with a suggested
structure and a plain-language explanation:

- **Shares**
- **ATM Calls**
- **Slightly-ITM Calls**
- **Call Debit Spread**
- **LEAPS**

It decides *how* to express a home run (cost / leverage / decay / capped-vs-open
payoff); it does **not** size portfolio risk or route orders (those stay with
`risk/` and `execution/`).

### Relationship to the other instrument engines

| Engine | Question | Output |
|---|---|---|
| `InstrumentSelectionEngine` | how to express *any* bullish thesis | shares / long_call / vertical_call_spread / leaps (from IV/RV) |
| `OptionsQualificationEngine` | is this *contract* tradeable? | QUALIFIED / REJECTED |
| **`HomeRunInstrumentSelector`** | **how to express a *home-run* trade** | **shares / ATM / slightly-ITM / spread / LEAPS (from IV *rank* + account size)** |

This selector is the finer-grained, home-run-tuned sibling of the general engine:
it splits the long call into **ATM vs slightly-ITM** and decides from **IV rank**
and **account size**, leaning toward convex, leveraged structures.

## 1. Decision factors → instrument

```
 Home-Run trade (qualified)                six decision factors
        │                          ┌───────────────────────────────────┐
        ▼                          │ expected move · time horizon ·     │
   HomeRunTrade ───────────────►   │ IV rank · options liquidity ·      │
        │                          │ account size · risk budget         │
        ▼                          └───────────────────────────────────┘
 HomeRunInstrumentSelector.recommend()
        │  1. normalize each factor → [0,1] sub-scores
        │  2. weighted blend per instrument (5 candidates)
        │  3. hard options-liquidity / LEAPS gates
        │  4. argmax (tie-break: simpler/less-aggressive first)
        ▼
 HomeRunRecommendation  →  instrument + structure + explanation
```

| Factor | Shares | ATM Calls | Slightly-ITM | Call Spread | LEAPS |
|---|---|---|---|---|---|
| **Expected move** | small ✓ | large ✓ | large ✓ | moderate ✓ | large ✓ |
| **Time horizon** | long/indefinite ✓ | short ✓ | medium ✓ | short–med ✓ | long ✓ |
| **IV rank** | rich → ✓ | **cheap → ✓** | moderate ✓ | **rich → ✓** | cheap → ✓ |
| **Liquidity** | (n/a) | gate | gate | gate | gate + LEAPS listed |
| **Account size** | ample ✓ | — | — | small ✓ | ample ✓ |
| **Risk budget** | ample ✓ | small ✓ (leverage) | small ✓ | tight ✓ | small ✓ |

The intuition: a home run wants **convexity/leverage**, but IV rank decides
*whether you buy it* (cheap → naked ATM/ITM calls or LEAPS) or *finance it*
(rich → call debit spread); horizon decides *how long* (short → near-dated calls,
long → LEAPS); liquidity, account size and risk budget gate and temper the choice;
shares are the linear fallback when options are illiquid, IV is rich on a long
hold, or the account/budget is large.

## 2. Suggested structure

Each recommendation carries an actionable (approximate) structure:

| Instrument | Target Δ | Expiry | Sizing |
|---|---|---|---|
| Shares | — | — | shares = risk_budget ÷ (price × assumed_stop_pct) |
| ATM Calls | ~0.50 | clamp(horizon, 30–120d) | total debit ≈ risk budget (defined risk) |
| Slightly-ITM Calls | ~0.65 | clamp(horizon, 30–120d) | total debit ≈ risk budget |
| Call Debit Spread | ~0.55 long / ~0.30 short | clamp(horizon, 30–120d) | net debit ≈ risk budget |
| LEAPS | ~0.75 | max(horizon, 365d) | total debit ≈ risk budget |

Option contract counts are intentionally left to fill from live quotes (the
defined risk is the premium, sized to the risk budget); shares are sized precisely
from a heuristic swing stop. Every expression risks ≈ the same `risk_budget`.

## 3. Usage

```python
from momentum.instruments import HomeRunInstrumentSelector, HomeRunTrade

trade = HomeRunTrade(
    symbol="NVDA", entry_price=120.0,
    expected_move_pct=0.45, horizon_days=30,
    iv_rank=0.12,                 # cheap vs its own 1y range -> buy premium
    options_liquidity=0.9, leaps_available=True,
    account_size=100_000.0, risk_budget=500.0,
)
rec = HomeRunInstrumentSelector().recommend(trade)
rec.instrument            # HomeRunInstrument.ATM_CALL
rec.structure             # target delta ~0.50, ~30d expiry, max_risk = budget
rec.explanation           # human-readable "why this instrument"
rec.candidates            # all five scores + factor breakdown
rec.to_dict()             # full record for the trade log
```

Example explanation:

```
Recommend ATM Calls for NVDA (home-run expression, score 0.96).
Primary drivers: iv 1.00, horizon 1.00.
Factors: expected move 45%, horizon 30d, IV rank 12% (cheap), account $100,000, risk budget $500.
Suggested structure: ~50%Δ ≈30d expiry.
Runner-up: Slightly-ITM Calls (margin 0.39).
```

Configuration (`HomeRunInstrumentConfig`) is immutable Pydantic with the factor
bands, per-instrument weights, structure targets and the liquidity gate, loadable
from `config/home_run_instrument.yaml` and hashable for reproducibility.

## 4. Tests

- **Selector** — each instrument wins under the conditions that should favour it
  (small move/long hold/rich IV → shares; big move/short/cheap IV → ATM; big
  move/medium/moderate IV → slightly-ITM; rich IV/moderate/small account → spread;
  long hold/big move/cheap IV → LEAPS); illiquid options force shares; no-LEAPS
  blocks LEAPS; structure & sizing; full recommendation object.
- **Config** — defaults, YAML load, overrides, validation/ordering, hash.
