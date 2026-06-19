# Home-Run-Opportunity Engine

> **Status: implemented.** Code in `src/momentum/opportunity/`; persistence in the
> `opportunity_classifications` table (migration `0007`); config template
> `config/opportunity.example.yaml`; tests in `tests/unit/opportunity/`.

This engine answers one question for every candidate trade: *could it produce an
outsized, positive-skew winner?* It blends six inputs into a 0-100 opportunity
score and classifies the setup into one of three tiers — **Normal**, **Enhanced**
or **Home Run** — directly serving the platform's objective (largest winner /
trend capture, not win rate). The **Home Run** tier is deliberately **rare —
under 5% of all signals** — and **every** classification is stored so the realized
rate can be audited.

## 1. Inputs → score → tier

```
 universe/ scanner (setup)         signals/ regime (context)      analytics/ history
        │                                  │                              │
        ▼                                  ▼                              ▼
  new ATH, relative volume,        market regime                 historical analogs
  sector leadership, momentum            │                       (mean R of similar
        └──────────────┬─────────────────┴──────────────┬───────── past setups)
                       ▼                                 ▼
              HomeRunOpportunityEngine.classify(OpportunityInputs)
                       │  1. blend 6 inputs -> 0-100 opportunity score
                       │  2. evaluate the hard Home-Run gates
                       │  3. score + gates -> tier
                       ▼
              OpportunityResult ──►  opportunity_classifications (DB)
              (tier, score, components, gate outcomes, reasons)
```

The six inputs (all optional; a missing input is scored *neutral* and fails the
Home-Run gate rather than passing it):

| Input | Field | Role |
|---|---|---|
| **New ATH** | `new_ath` (+ `distance_to_ath`) | blue-sky breakout — the signature of a home run; partial credit when merely near the high |
| **Relative Volume** | `relative_volume` | participation / conviction behind the move |
| **Sector Leadership** | `sector_leadership` | is the move backed by a leading sector? |
| **Market Regime** | `market_regime` | is there a market tailwind? (neutral is penalised; bear ≈ 0) |
| **Momentum** | `momentum_score` | strength of the trend being entered |
| **Historical Analogs** | `historical_expectancy_r` (+ `historical_sample_size`) | when we took setups like this before, did they pay off big? (small samples shrink toward neutral) |

The score is a transparent weighted blend — component contributions sum exactly to
the score, so every assessment is explainable.

## 2. The three tiers (and why Home Runs are rare)

| Tier | Condition |
|---|---|
| **Home Run** | `score ≥ home_run_min_score` **AND** every hard gate passes |
| **Enhanced** | `score ≥ enhanced_min_score` |
| **Normal** | otherwise |

The Home-Run **hard gates** must hold *simultaneously* (defaults shown):

- a **confirmed new all-time high** (`home_run_require_new_ath`)
- a **bull regime** (`home_run_min_regime_score = 1.0`)
- **relative volume ≥ 2.0×** (`home_run_min_relative_volume`)
- **momentum ≥ 0.80** (`home_run_min_momentum`)

Requiring the conjunction of these individually-uncommon conditions — on top of a
top-decile score — is what holds the Home-Run rate under the
`target_home_run_rate` (5%). Rarity is not left to chance: it is **calibrated and
verifiable** (§4).

## 3. Database schema (`opportunity_classifications`, migration 0007)

One row per classified setup — **every** signal, not just Home Runs, so the tier
mix is auditable.

| Column | Meaning |
|---|---|
| `run_id`, `signal_id`, `trade_id`, `symbol`, `as_of`, `ts` | linkage |
| `tier` | `normal` \| `enhanced` \| `home_run` |
| `score` | 0-100 opportunity score |
| `new_ath` | raw breakout flag |
| `new_ath_score`, `momentum_score`, `relative_volume`, `regime_score`, `sector_leadership`, `historical_edge` | the six normalized component scores |
| `model_version`, `config_hash` | reproducibility |
| `breakdown` (JSON) | full per-component contributions, gate outcomes and reasons |

`OpportunityClassificationRepository` provides `save_result`, `for_symbol`,
`by_tier`, `tier_mix` and `home_run_rate` (the headline rarity metric).

## 4. Calibrating & verifying rarity

`momentum.opportunity.calibration` makes "< 5%" measurable and enforceable:

```python
from momentum.opportunity import (
    HomeRunOpportunityEngine, calibrate_home_run_min_score, verify_rarity,
)

# 1. Calibrate the score threshold against a representative window of signals so
#    at most `target` of them can clear it (the gates only push the rate lower).
cfg = calibrate_home_run_min_score(recent_inputs, target_home_run_rate=0.05)
engine = HomeRunOpportunityEngine(cfg)

# 2. Classify, persist every result, and verify the realized mix.
results = [engine.classify(i) for i in recent_inputs]
report = verify_rarity(results, target_home_run_rate=cfg.tiers.target_home_run_rate)
report.home_run_rate   # e.g. 0.018
report.ok              # True  (<= target)
```

`calibrate_home_run_min_score` sets `home_run_min_score` to the `(1 - target)`
quantile of the sample's scores, so by construction at most `target` of the sample
scores at/above it — and the hard gates remove more — guaranteeing the realized
Home-Run rate cannot exceed the target on that sample.

## 5. Usage

```python
from momentum.opportunity import HomeRunOpportunityEngine, OpportunityInputs

inputs = OpportunityInputs(
    market_regime="bull", new_ath=True, relative_volume=2.6,
    sector_leadership=0.9, momentum_score=0.92,
    historical_expectancy_r=1.1, historical_sample_size=25,
)
result = HomeRunOpportunityEngine().classify(inputs)
result.tier            # OpportunityTier.HOME_RUN
result.score           # ~96
result.reasons         # human-readable tier explanation
result.failed_gates    # () — all Home-Run gates passed
result.to_dict()       # full breakdown for the trade log

# Build inputs straight from the platform's own models:
inputs = OpportunityInputs.from_sources(scan_result, regime, similar_setups)
```

Configuration (`OpportunityConfig`) is immutable Pydantic with the six weights,
per-input normalization ranges and the tier cut-offs/gates, loadable from
`config/opportunity.yaml` and hashable (`config_hash()`) for reproducibility.

## 6. Scope

Pure and self-contained (the engine depends only on `config`/`inputs`; the
`from_sources` builder and persistence reuse the existing scan/regime/trade
models). It **classifies** opportunity — it does not size positions, choose the
instrument or route orders (those stay with `risk/`, `instruments/` and
`execution/`). It pairs naturally with the conviction engine: conviction asks
*how strong is this setup?*, this engine asks *how big could it get?*

## 7. Tests

- **Engine** — perfect inputs → Home Run; missing inputs → Normal; each hard gate
  blocks the Home-Run tier in isolation (no new ATH, neutral regime, thin volume,
  weak momentum) and the setup falls back to Enhanced; contributions sum to score;
  monotonicity; explanations.
- **Config** — defaults, YAML load, validation, ordering, hash.
- **Calibration** — over a large, seeded, representative population the realized
  Home-Run rate is under 5%; `calibrate_home_run_min_score` tightens an
  over-loose config to meet the target; `verify_rarity` reporting.
- **Persistence** — round-trip, `tier_mix`, `home_run_rate`, schema columns.
