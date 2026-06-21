# Momentum Scanner — Design & Reference

Screens the US equity universe and ranks the strongest momentum candidates.

> **Status: implemented.** Code: `src/momentum/universe/` (`screener.py`,
> `filters.py`, `scanner_config.py`) with indicators in
> `src/momentum/signals/`. Results persist to the `scan_results` table
> (`models/scan_result.py`, migration `0002`, `repositories/scans.py`).
> Config template: `config/scanner.example.yaml`.

---

## 1. Pipeline

```
bars (symbol -> OHLCV)
      │  ① features        per symbol: price, $-vol, rel-vol, ATH distance,
      ▼                    20/50/200 EMA, ATR, realized vol + IV rank,
                           blended momentum, sector
   features table
      │  ② score           cross-sectional 0..100 composite (weighted)
      ▼
      │  ③ filter          hard gates (price, liquidity, rel-vol, ATH, EMA stack, sector RS)
      ▼
      │  ④ rank            survivors by score, rank 1 = strongest
      ▼
   ScanResult ──► to_records() ──► scan_results table
```

`MomentumScanner.scan(bars, sectors=..., as_of=...)` returns a `ScanResult`
(DataFrame-backed, fully auditable) whose `.candidates` are ranked
`ScanCandidate` objects.

## 2. Filters (all configurable)

| Filter | Default | Config key |
|---|---|---|
| Price > $5 | `5.0` | `filters.min_price` |
| Avg daily $ volume (liquidity) | `$20M` | `filters.min_dollar_volume` |
| Relative volume ≥ | `1.0×` | `filters.min_relative_volume` |
| Within X% of all-time high | `25%` | `filters.max_distance_from_ath` |
| 20 EMA > 50 EMA | on | `filters.require_ema_fast_above_mid` |
| 50 EMA > 200 EMA | on | `filters.require_ema_mid_above_slow` |
| Sector relative strength ≥ | `0.50` | `filters.min_sector_rs` |

Filters are individually-testable predicates (`universe/filters.py`) combined by
`combine()`, which also reports how many symbols each gate eliminated — useful
for tuning. A symbol with no sector mapping is **not** dropped by the sector gate.

## 3. Momentum score (0..100)

A weighted blend of cross-sectional components, re-normalized over whichever are
available per symbol:

| Component | Meaning | Weight |
|---|---|---|
| `momentum` | percentile of blended 3/6/12-month return | 0.40 |
| `trend` | EMA-stack alignment (price>20>50>200), 0..1 | 0.20 |
| `ath_proximity` | closeness to the all-time high, 0..1 | 0.15 |
| `relative_volume` | percentile of relative volume | 0.10 |
| `sector_rs` | sector's mean momentum percentile | 0.15 |

**Sector relative strength** is computed from the universe itself: each symbol
gets its *sector's* average momentum percentile (0.5 = an average sector), so
leaders in collectively strong sectors score higher — no external sector index
required.

## 4. API

```python
from momentum.data import YahooProvider, BarCache, DataIngestor, Timeframe
from momentum.universe import MomentumScanner, ScannerConfig

ing = DataIngestor(YahooProvider(), BarCache("data/cache"))
bars = {s: ing.load(s, "2021-01-01", "2024-12-31", Timeframe.DAY) for s in symbols}

scanner = MomentumScanner(ScannerConfig.from_yaml("config/scanner.yaml"))
result = scanner.scan(bars, sectors=sector_map)

for c in result.top(20):
    print(c.rank, c.symbol, round(c.momentum_score, 1))
```

### Persisting

```python
from momentum.persistence.database import create_db_engine, create_session_factory, session_scope
from momentum.persistence.repositories.scans import ScanResultRepository

factory = create_session_factory(create_db_engine())
with session_scope(factory) as session:
    ScanResultRepository(session).save_scan(result, run_id="eod-2024-12-31")
```

`save_scan` is idempotent per `(run_id, as_of)` — re-running replaces prior rows.
Query back with `top_for_date(date, n)` or `for_run(run_id)`.

## 5. Configuration

`ScannerConfig` is immutable Pydantic (loadable from YAML/dict, `config_hash()`
for reproducibility) with strict validation: `ema_fast < ema_mid < ema_slow`,
non-negative / non-all-zero score weights, bounded distances, and non-empty
momentum lookbacks. See `config/scanner.example.yaml`.
