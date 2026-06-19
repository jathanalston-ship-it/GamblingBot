# Conviction Scoring Engine

Scores every candidate setup **0–100** from eight inputs and assigns a band.
Fully explainable (per-component contributions sum to the score) and persisted to
the `conviction_scores` table. Config: `config/conviction.example.yaml`.

```
LOW  [0, 40)   MEDIUM  [40, 70)   HIGH  [70, 85)   EXTREME  [85, 100]
```
(Boundaries are lower-inclusive on the upper edge.)

## Inputs and normalization

Each raw input is mapped to `[0, 1]` (clamped). A **missing** input contributes a
*neutral* `0.5` rather than `0`, so partial evidence neither inflates nor tanks
conviction.

| # | Input | Source (typical) | Mapping to [0, 1] |
|---|---|---|---|
| 1 | Market regime | `MarketRegime.regime` | label map: bull 1.0 / neutral 0.5 / bear 0.0 |
| 2 | Sector strength | `ScanResult.sector_rs` | linear 0 → 1 |
| 3 | Relative volume | `ScanResult.relative_volume` | linear 1.0 → 3.0 |
| 4 | Distance to ATH | `ScanResult.distance_from_ath` | inverted: at ATH → 1, ≥20% below → 0 |
| 5 | Trend strength | ADX (regime proxy) | linear 15 → 40 |
| 6 | Breadth | `MarketRegime.breadth` | linear 0.30 → 0.70 |
| 7 | Momentum score | `ScanResult.momentum_score` | linear 0 → 1 |
| 8 | Historical similar setups | closed-trade history | expectancy (R) mapped −0.5 → 1.0, **shrunk toward neutral** by `min(1, n / 20)` |

The eighth input is computed by `SimilarSetupAnalyzer`: it pulls closed trades
matching the setup's regime / sector (optionally symbol) and returns their mean
R, win rate and **sample size** — so a strong-but-thin history is trusted only
partially.

## Score

```
score = 100 · Σ(normalizedᵢ · weightᵢ) / Σ(weightᵢ)
contributionᵢ = normalizedᵢ · weightᵢ / Σ(weight) · 100   (Σ contributions = score)
band = LOW | MEDIUM | HIGH | EXTREME  (from the score cut-offs)
```

Default weights lead with **regime (0.18)** and **momentum (0.18)**; all weights
and cut-offs are config (`ConvictionConfig`, hashed for reproducibility).

## Usage

```python
from momentum.conviction import ConvictionEngine, ConvictionInputs, SimilarSetupAnalyzer
from momentum.persistence.repositories.conviction_scores import ConvictionScoreRepository

similar = SimilarSetupAnalyzer(session).analyze(regime="bull", sector="Technology")
inputs = ConvictionInputs.from_sources(scan_result, regime, similar)   # or construct directly
result = ConvictionEngine().score(inputs)        # -> ConvictionResult(score, band, components, ...)

ConvictionScoreRepository(session).save_result(
    result, symbol="AAPL", run_id=run_id, as_of=as_of, trade_id=trade.id,
)
```

## Storage — `conviction_scores` (migration `0006`)

| Group | Columns |
|---|---|
| Identity | `id`, `run_id`, `symbol`, `as_of`, `ts`, `trade_id`→trades, `signal_id`→signals |
| Result | `score`, `band`, `model_version`, `config_hash` |
| Components (normalized 0..1) | `regime_score`, `sector_strength`, `relative_volume`, `distance_to_ath`, `trend_strength`, `breadth`, `momentum_score`, `historical_edge` |
| Explainability | `breakdown` (JSON: per-component raw / normalized / weight / contribution) |
| Audit | `created_at`, `updated_at` |

Indexed on `symbol`, `band`, `as_of`, `run_id`, `score`, the FKs, and the
composites `(symbol, as_of)` and `(run_id, band)`. Repository:
`ConvictionScoreRepository` (`save_result`, `for_symbol`, `by_band`, `top`).
