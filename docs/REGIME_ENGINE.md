# Market Regime Engine — Design & Reference

The single component that answers one question for the whole platform:

> **Are conditions favorable for aggressive momentum trading?**

Output is a three-way label — **Bullish** / **Neutral** / **Bearish** — backed by
a continuous score, a confidence, and the full per-factor evidence.

> **Status: implemented.** Code lives in `src/momentum/signals/regime.py` and
> `regime_config.py`; tests in `tests/unit/signals/`. Configuration template:
> `config/regime.example.yaml`.

---

## 1. Why it exists

The strategy layer is deliberately *blind* to the macro backdrop — it only emits
"breakout here". Whether the platform acts aggressively on those breakouts is a
separate, centralized decision. Momentum strategies make their money in calm,
trending, broad-participation markets and give it back in choppy, high-volatility,
narrow ones. The regime engine is the gate:

| Regime | Meaning | Intended use |
|---|---|---|
| **Bullish** | Trend up, broad participation, calm vol | Full risk; take breakouts aggressively |
| **Neutral** | Mixed / transitional | Reduced conviction; smaller size, fewer names |
| **Bearish** | Downtrend, narrow, high vol | Stand aside / defensive; suppress new entries |

It is intentionally **transparent and bounded** — no black box. Every input maps
to a score in `[-1, +1]`, and the composite is a plain weighted mean, so any
verdict can be read off its factor table and reproduced from the config hash.

---

## 2. Inputs

| Input | Type | Source | What it captures |
|---|---|---|---|
| **SPY** | OHLCV frame | `momentum.data` | Broad-market trend structure |
| **QQQ** | OHLCV frame | `momentum.data` | Growth / tech leadership |
| **Market breadth** | scalar `0..1` | breadth feed | Advance/decline participation |
| **New highs** | scalar | breadth feed | 52-week new-high count |
| **New lows** | scalar | breadth feed | 52-week new-low count |
| **VIX** | scalar | data feed | Implied volatility (fear) |
| **50-day participation** | scalar `0..1` | universe scan | % of universe above its 50DMA |
| **200-day participation** | scalar `0..1` | universe scan | % of universe above its 200DMA |

SPY/QQQ are passed as the canonical OHLCV DataFrames produced by the data layer
(a bare close `Series` is also accepted). Every scalar may be a single value or a
`Series` (the latest value is used). **Any input may be omitted** — its factor is
dropped and the remaining weights re-normalize.

---

## 3. Scoring system

### 3.1 Per-factor scores → `[-1, +1]`

Each factor is mapped to a sub-score where `-1` is maximally bearish, `+1`
maximally bullish, `0` neutral.

**Trend (SPY, QQQ).** Three classic, bounded checks combine into one score
(`trend_score`):

| Check | Weight | +1 when | −1 when |
|---|---|---|---|
| Price vs **200DMA** (the gate) | 0.5 | price > 200DMA | price < 200DMA |
| Price vs **50DMA** | 0.3 | price > 50DMA | price < 50DMA |
| **50DMA vs 200DMA** (golden cross) | 0.2 | 50 > 200 | 50 < 200 |

A clean uptrend (price above both rising MAs) → `+1`. If history is too short for
the 200DMA, that check is dropped and the rest re-normalize, so a young series
still scores from what's available.

**Continuous factors** use a piecewise-linear ramp `linear_score(v, low, high)`:
`v ≤ low → −1`, `v ≥ high → +1`, linear in between (midpoint → 0).

| Factor | Mapping | Default band |
|---|---|---|
| **Breadth** | ascending | bear `0.40` … bull `0.60` |
| **New highs/lows** | `index = (NH−NL)/(NH+NL)`, ascending | bear `−0.20` … bull `+0.20` |
| **VIX** | **descending** (calm = bullish) | calm `15` (+1) … stress `28` (−1) |
| **50-day participation** | ascending | bear `0.40` … bull `0.60` |
| **200-day participation** | ascending | bear `0.40` … bull `0.60` |

The VIX is the only inverted factor: low implied vol favors trend-following, so
`linear_score(vix, 15, 28, ascending=False)`.

### 3.2 Composite

```
composite = Σ(weightᵢ · scoreᵢ) / Σ(weightᵢ)     over factors present
```

Because each `scoreᵢ ∈ [-1, +1]` and weights are re-normalized over the available
factors, the composite is always in `[-1, +1]` regardless of which inputs are
supplied.

Default weights (need not sum to 1):

| Factor | Weight |
|---|---|
| SPY trend | 0.25 |
| 200-day participation | 0.15 |
| QQQ trend | 0.15 |
| VIX | 0.15 |
| Breadth | 0.10 |
| New highs/lows | 0.10 |
| 50-day participation | 0.10 |

### 3.3 Label

```
composite ≥ bull_score (default +0.20)  → Bullish
composite ≤ bear_score (default −0.20)  → Bearish
otherwise                               → Neutral
```

### 3.4 Confidence

```
confidence = 0.6 · strength + 0.4 · agreement
  strength  = min(1, |composite|)                  # how decisive
  agreement = share of factors agreeing with sign  # how unanimous
```

A strong, unanimous reading approaches `1.0`; a weak or internally-conflicted
reading stays low even if it crosses a label threshold.

### 3.5 Component states

Two sub-labels accompany the headline (and map onto the `market_regimes` table):

* **trend_state** ∈ {uptrend, sideways, downtrend} — from the average of the
  SPY/QQQ trend scores (`trend_up = +0.34`, `trend_down = −0.34`).
* **volatility_state** ∈ {low, normal, high, extreme} — from the VIX
  (`<15` low, `<25` normal, `<35` high, else extreme).

---

## 4. Worked example

```text
SPY: price above rising 50 & 200DMA          spy_trend     = +1.00  · 0.25
QQQ: same                                    qqq_trend     = +1.00  · 0.15
Breadth = 0.70                               breadth       = +1.00  · 0.10
NH=300, NL=20 → index +0.82                  new_high_low  = +1.00  · 0.10
VIX = 13  (< 15)                             vix           = +1.00  · 0.15
% > 50DMA = 0.75                             participation_50  = +1.00 · 0.10
% > 200DMA = 0.70                            participation_200 = +1.00 · 0.15
                                             -----------------------------
composite = +1.00  ≥ +0.20  →  BULLISH       confidence = 1.00
                                             trend = uptrend, vol = low
```

A bearish mirror (downtrend, VIX 34, participation 0.20, NL ≫ NH) yields
`composite = −1.00 → Bearish`, while genuinely mixed inputs land in `Neutral`
with low confidence.

---

## 5. Configuration system

All tunables are immutable Pydantic models (`regime_config.py`), loadable from
YAML or a dict and hashable for run reproducibility.

```python
from momentum.signals import RegimeConfig

cfg = RegimeConfig.from_yaml("config/regime.yaml")   # or RegimeConfig() for defaults
cfg = RegimeConfig.from_dict({"ma_fast": 20, "weights": {"vix": 0.5}})
cfg.config_hash()        # stable 16-char hash of the full config
```

* `RegimeConfig` — `model_version`, `benchmark_symbol`, `ma_fast` (50),
  `ma_slow` (200), plus nested `weights` and `thresholds`.
* `FactorWeights` — the seven non-negative factor weights.
* `RegimeThresholds` — every cutoff in §3, with validation that bands are
  correctly ordered (e.g. `bear_score < bull_score`, `vix_calm < vix_stress`,
  `vix_low < vix_high < vix_extreme`).

Validation is strict: unknown keys, negative weights, all-zero weights,
mis-ordered bands, or `ma_fast ≥ ma_slow` all raise `ValidationError` at load
time. Models are frozen, so a loaded config cannot mutate mid-run. See
`config/regime.example.yaml` for the fully-annotated template.

---

## 6. Python API

```python
from momentum.data import YahooProvider, BarCache, DataIngestor, Timeframe
from momentum.signals import RegimeEngine, RegimeConfig

# 1. get index history through the data layer
ing = DataIngestor(YahooProvider(), BarCache("data/cache"))
spy = ing.load("SPY", "2015-01-01", "2024-12-31", Timeframe.DAY)
qqq = ing.load("QQQ", "2015-01-01", "2024-12-31", Timeframe.DAY)

# 2. classify
engine = RegimeEngine(RegimeConfig.from_yaml("config/regime.yaml"))
result = engine.evaluate(
    spy, qqq,
    vix=13.5,
    breadth=0.68,
    new_highs=240, new_lows=35,
    pct_above_50dma=0.72,
    pct_above_200dma=0.65,
)

if result.is_favorable:        # True only when Bullish
    ...                        # take breakouts at full risk

print(result)                  # <Regime Bullish score=+0.81 conf=0.92 ... >
result.to_dict()               # JSON-friendly verdict + factor breakdown
result.to_record()             # kwargs ready for the market_regimes table
```

### Key objects

| Object | Purpose |
|---|---|
| `RegimeEngine.evaluate(...)` | Point-in-time classification → `RegimeResult` |
| `RegimeResult` | `state`, `score`, `confidence`, `trend_state`, `volatility_state`, `factors`, `is_favorable`, `to_dict()`, `to_record()` |
| `FactorScore` | One factor's `name`, `score`, normalized `weight`, `raw` value, `contribution` |
| `RegimeState` | `BULLISH` / `NEUTRAL` / `BEARISH` enum (`.is_favorable`, `.display`) |
| `linear_score`, `trend_score`, `high_low_index` | The pure scoring primitives, independently testable |

`evaluate(as_of=...)` slices SPY/QQQ to a date for point-in-time / backtest use,
guaranteeing no look-ahead beyond the supplied bar.

---

## 7. Persistence mapping

`RegimeResult.to_record()` returns kwargs aligned 1:1 with the existing
`market_regimes` table (`docs/SCHEMA.md`): `as_of`, `benchmark_symbol`,
`model_version`, `regime`, `trend_state`, `volatility_state`, `score`,
`confidence`, `benchmark_close`, `ma_fast`, `ma_slow`, `breadth`, and a `details`
JSON blob of the per-factor scores. One row per `(as_of, benchmark, model_version)`
makes every classification auditable and lets backtests attribute performance by
regime.

---

## 8. Design choices & extension points

* **Weighted linear scoring over ML.** Auditable, reproducible, and debuggable —
  you can always explain *why* a day was Bearish. A learned classifier could later
  sit behind the same `RegimeEngine` surface without touching callers.
* **Graceful degradation.** Missing feeds (no breadth, short history) shrink the
  evidence set rather than crashing; weights re-normalize so the verdict stays in
  range.
* **Adding a factor** is: compute its `[-1, +1]` score, add a weight to
  `FactorWeights`, add any thresholds to `RegimeThresholds`, and include it in
  `RegimeEngine.evaluate`. Nothing downstream changes.
* **Hysteresis (future).** To avoid whipsawing between labels on borderline days,
  a future version may require N consecutive crossings before flipping the
  headline — deliberately omitted now to keep the v1 mapping pure and stateless.
```
