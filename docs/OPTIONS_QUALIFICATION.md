# Options Qualification Engine

> **Status: implemented.** Code in `src/momentum/instruments/qualification.py`
> and `qualification_config.py`; config template
> `config/options_qualification.example.yaml`; tests in
> `tests/unit/instruments/test_qualification*.py`.

A trade may only be expressed with **options** when the concrete contract is
actually tradeable. This engine is a hard **pass/fail gate**: it takes one
option contract's market snapshot and returns a **`QUALIFIED`** or
**`REJECTED`** verdict with a per-gate breakdown and a human-readable reason for
every failure. It scores nothing and ranks nothing — that is the job of the
[instrument-selection engine](INSTRUMENT_SELECTION.md), which decides *whether*
to use options at all. Qualification is the safety check on the specific
contract that selection would route.

## 1. The gates

A contract is **`QUALIFIED`** only if it clears **all** of:

| # | Gate | Rule | Why |
|---|---|---|---|
| 1 | **Open interest** | `open_interest > min_open_interest` | enough resting size to enter and exit |
| 2 | **Bid/ask spread** | `spread / mid < max_spread_pct` | round-trip slippage stays small |
| 3 | **Volume** | `volume > min_volume` | the contract is actually trading today |
| 4 | **Days to expiry** | `days_to_expiry > min_days_to_expiry` | avoid expiration-week theta/pin risk |
| 5 | **Implied vol** | `implied_vol < max_implied_vol` | not a blow-off / un-hedgeable premium |
| 6 | **Gamma risk** | `shock_delta ≤ max_gamma_shock_delta` | delta is stable enough to manage |

The liquidity/expiry/IV gates are plain hard floors and ceilings (the floors use
strict `>`, matching "greater than a threshold"). The gamma gate is the only
derived one.

### Gamma risk

Raw gamma is not comparable across underlyings (it scales inversely with spot),
so the gate measures **delta drift on a configurable underlying shock** instead:

```
shock_delta = |gamma| · underlying_price · gamma_shock_pct
```

i.e. *how much would this option's delta move on a `gamma_shock_pct` move in the
underlying?* This is scale-free across price levels. A contract is acceptable
while `shock_delta ≤ max_gamma_shock_delta`. Near-expiry ATM options (gamma
spikes, pin risk) fail; ordinary 30–60 DTE contracts pass.

If `gamma` or `underlying_price` is missing, the gate is **skipped with a note**
by default; set `require_greeks: true` to reject contracts with no greeks
instead.

Every gate is evaluated — the engine does **not** short-circuit — so a rejection
reports *all* the reasons a contract failed, not just the first.

## 2. Inputs & output

```
OptionQuote (one contract snapshot)                OptionsQualificationConfig
  symbol, days_to_expiry,                            (thresholds, immutable
  open_interest, volume, bid, ask, implied_vol,       Pydantic, YAML-loadable)
  gamma?, underlying_price?, delta?, strike?, right?         │
        │                                                    ▼
        └──────────────►  OptionsQualificationEngine.qualify()
                                       │
                                       ▼
                          OptionsQualification
                          (verdict, per-gate checks, reasons, to_dict)
```

`OptionsQualification` exposes `qualified` / `rejected`, `reasons` (failed-gate
details), `failed_gates` (names), `check(name)` (one gate), and `to_dict()` for
logging/serialization (non-finite values such as an undefined spread collapse to
`null`, so the dict is always JSON-safe).

## 3. Usage

```python
from momentum.instruments import OptionQuote, OptionsQualificationEngine

engine = OptionsQualificationEngine()           # or pass an OptionsQualificationConfig

quote = OptionQuote(
    symbol="AAPL", days_to_expiry=45,
    open_interest=5_000, volume=1_200,
    bid=2.00, ask=2.06,                         # ~3% spread of mid
    implied_vol=0.45,                           # 45% annualized
    gamma=0.03, underlying_price=190.0,         # shock delta = 0.285
)

result = engine.qualify(quote)
result.qualified          # True
result.verdict            # QualificationVerdict.QUALIFIED
result.reasons            # () — populated with each failure when rejected
result.to_dict()          # JSON-safe record for the trade log

engine.is_qualified(quote)   # convenience bool
```

A rejection is just as legible:

```python
bad = engine.qualify(OptionQuote("XYZ", 2, 50, 10, 0.10, 0.40, 2.5))
bad.rejected        # True
bad.failed_gates    # ('open_interest', 'bid_ask_spread', 'volume',
                    #  'days_to_expiry', 'implied_vol')
bad.reasons         # one explanatory string per failed gate
```

Configuration (`OptionsQualificationConfig`) is immutable Pydantic, loadable from
`config/options_qualification.yaml` and hashable (`config_hash()`) for run
reproducibility — the platform-wide config pattern.

## 4. Scope

Pure and self-contained (depends only on `core`). It vets a contract; it does
**not** size the position or route the order (that stays with `risk/` and
`execution/`), and it does **not** choose shares-vs-options (that is
`instruments/` selection). Persisting qualification verdicts to the trade log is
a natural future extension — `OptionsQualification.to_dict()` already produces
the record.

## 5. Tests

- **Engine** — a clean contract qualifies; each gate rejects in isolation
  (low OI, wide/absent/crossed spread, thin volume, near expiry, extreme IV,
  high gamma); missing greeks skip-by-default vs `require_greeks`; strict-floor
  boundaries; all failures reported (no short-circuit); JSON-safe `to_dict()`.
- **Config** — defaults, YAML load, dict override, immutability, hash
  sensitivity, forbidden extra keys, field-bound validation.
