# Dynamic Risk Budget Engine

> **Status: implemented.** Code in `src/momentum/risk/risk_budget.py` and
> `risk_budget_config.py`; config template `config/risk_budget.example.yaml`;
> tests in `tests/unit/risk/test_risk_budget*.py`.

This engine decides **how much risk a single trade may take** — its per-trade
risk budget (a fraction of equity, and the dollar amount) — from the trade's
**conviction** and **opportunity tier**, then clamps that to the room left under
the **portfolio-heat ceiling**. It is the bridge between the conviction /
home-run engines and position sizing: its `granted_pct` is the risk-per-trade the
risk gateway then sizes from.

## 1. Policy

| Driver | Budget |
|---|---|
| Base (low / medium conviction) | **0.5%** |
| High conviction | **1%** |
| Extreme conviction | **2%** |
| **Home-Run** trade | conviction base **× 1.5** (e.g. extreme → 3%), capped per-trade |
| Per-trade ceiling | **3%** (`max_trade_risk_pct`) |
| **Maximum portfolio risk (heat)** | **5%** — every budget clamps to the remaining headroom |

Home-Run trades *may receive a larger allocation* (the multiplier), **but must
remain within the portfolio heat limit**: the granted budget is never more than
`max_portfolio_heat − heat_already_used`, so the book's aggregate open risk can
never breach 5%. When the book is already at the cap, a Home-Run trade gets **0**.

## 2. How a budget is computed

```
 conviction band ─┐
                  ├─► base %  (0.5 / 1 / 2)
 opportunity tier ┘        │
                           ├─ × tier multiplier (Home-Run ×1.5)
                           ├─ min(…, max_trade_risk_pct)        ← per-trade ceiling
                           ├─ × throttle (drawdown / regime, ≤1) ← optional
                           ▼
                     requested %
                           │
        portfolio heat ──► min(requested %, 5% − heat_used)      ← portfolio-heat clamp
                           ▼
                     granted %  →  risk $ = granted % × equity
```

The `throttle` (≤ 1) is an optional hook so the drawdown / regime scaling that the
risk gateway already applies composes cleanly on top of the conviction budget.

Each `RiskBudget` records the `base_pct`, `requested_pct`, `granted_pct`,
`risk_dollars`, the `binding_constraint` (`portfolio_heat` | `max_trade_risk` |
`None`), `portfolio_heat_after`, and a plain-language `reasons` trail.

## 3. Worked examples (equity $100k)

| Conviction | Tier | Heat used | Granted | Binding |
|---|---|---|---|---|
| High | — | 0% | 1.0% ($1,000) | — |
| Extreme | — | 0% | 2.0% ($2,000) | — |
| Extreme | **Home Run** | 0% | **3.0% ($3,000)** | — |
| Extreme | **Home Run** | 4% | **1.0% ($1,000)** | `portfolio_heat` |
| Extreme | **Home Run** | 5% | 0% ($0) | `portfolio_heat` |
| High | — | 0% (throttle 0.5) | 0.5% ($500) | — |

## 4. Usage

```python
from momentum.conviction.engine import ConvictionBand
from momentum.opportunity.engine import OpportunityTier
from momentum.risk import DynamicRiskBudgetEngine, RiskBudgetRequest

engine = DynamicRiskBudgetEngine()                 # or pass a RiskBudgetConfig

budget = engine.budget(RiskBudgetRequest(
    equity=100_000.0,
    portfolio_heat_used=0.04,                      # 4% heat already open
    conviction_band=ConvictionBand.EXTREME,
    opportunity_tier=OpportunityTier.HOME_RUN,
    symbol="NVDA",
))
budget.granted_pct        # 0.01  (3% wanted, clamped to the 1% heat headroom)
budget.risk_dollars       # 1000.0
budget.binding_constraint # "portfolio_heat"
budget.reasons            # human-readable trail
budget.to_dict()          # record for the trade log

# Straight from the live account (reads its portfolio heat):
budget = engine.budget(RiskBudgetRequest.from_account(
    account, conviction_band=ConvictionBand.HIGH, opportunity_tier=OpportunityTier.HOME_RUN,
))
```

The conviction band comes from the **conviction engine** and the opportunity tier
from the **Home-Run-opportunity engine**, tying the three together.

### Composition with the risk gateway

`DynamicRiskBudgetEngine` sits *in front of*
`RiskManager` — feed `budget.granted_pct` as the per-trade risk for sizing. Their
heat ceilings are the same number (`max_portfolio_heat`), so the gateway's own
heat check is a consistent second line of defence rather than a conflicting one.

Configuration (`RiskBudgetConfig`) is immutable Pydantic — every percentage and
multiplier is tunable, loadable from `config/risk_budget.yaml`, and hashable for
reproducibility. Validation enforces `base ≤ high ≤ extreme ≤ max_trade ≤
max_portfolio_heat`.

## 5. Tests

- **Engine** — the conviction tiers (0.5 / 1 / 2%); the Home-Run bump and its
  per-trade cap; Enhanced (off by default / configurable); the heat clamp
  (headroom, full book → 0, over-cap → 0); throttle composition; `from_account`;
  a parametrized invariant that no budget can push aggregate heat past 5%;
  `to_dict` / `__str__`.
- **Config** — defaults, YAML load, overrides, immutability, hash, and the
  ordering/ceiling validation rules.
