# Options Recommendation Engine

For an options-**eligible** setup (one that cleared the
[options-eligibility](OPTIONS_ELIGIBILITY.md) gate), recommend a single,
**defined-risk, conservative** options structure and the concrete contract to
express it with. It is read-only research — it **never** routes an order and ships
explicit risk disclosures with every recommendation.

This is the *which contract* step that sits between the eligibility gate (*whether*
to use options at all) and the contract-level
[options-qualification](OPTIONS_QUALIFICATION.md) gate (a hard pass/fail on a live
quote).

## Output

For the recommended structure the engine returns:

- **Expiration** (days to expiry)
- **Strike** (and the short strike for a spread)
- **Delta** (long-leg target delta, plus the short-leg delta for a spread)
- **Risk Level** — Low / Medium / High
- **Max Loss** ($ for the sized position)
- **Target Profit** ($ at the expected-move target)
- **Suggested Allocation** ($ premium outlay and % of equity, with a contract count)

…plus the per-structure suitability scores (transparency), the AVOID-gate
breakdown, a plain-language summary and the **risk disclosures**.

## Preference order

Structures are considered in the fixed platform order — Deep ITM is the
conservative default and the engine only steps away on a clear implied-volatility
signal:

1. **Deep ITM Calls** — high delta (~0.80), low theta; behaves like a leveraged
   stock. The default for most setups.
2. **ATM Calls** — chosen when IV is **cheap** (rank ≤ `iv_low`) *and* the expected
   move is large: maximum convexity per dollar.
3. **Vertical Call Spreads** — chosen when IV is **rich** (rank ≥ `iv_high`): sell
   upside to finance the long leg; defined and capped risk.

## What it AVOIDS

| Avoid | How it's enforced |
|---|---|
| **Low liquidity** | hard gate — underlying ADV must clear `min_underlying_dollar_volume`, else no recommendation |
| **Wide spreads** | hard gate — estimated option bid/ask (override or a liquidity proxy) must be ≤ `max_option_spread_pct` |
| **Lottery contracts** | by construction — the long delta is always ≥ `min_long_delta` (never far-OTM) |
| **Short-dated options** | by construction — the expiration is floored at `min_dte` (≥ 30d by default) |

A failed hard gate (liquidity, spread, or an ineligible setup) sets
`recommended = False` and the summary explains why; the would-be contract is still
returned for transparency.

## Pricing (approximate, no chain)

With no live option chain, premiums are approximated only to **size and compare**
structures, anchored on the Brenner–Subrahmanyam ATM proxy
`C_atm ≈ coeff · S · σ · √T` (σ from IV, else `ATR%·√252`, else a fallback).
In-/out-of-the-money extrinsic is scaled from the ATM extrinsic by `4·d·(1−d)` and
intrinsic added for ITM calls; target profit uses a conservative intrinsic-only
value at the expected-move target. These approximations are surfaced as a risk
disclosure — verify on the live chain before trading.

## Sizing

Debit structures: **max loss = premium paid**. The position is sized to the smaller
of (a) the per-trade **risk budget** (`floor(budget / max-loss-per-contract)`) and
(b) a **capital cap** (`max_capital_pct` of account equity). If even one contract
exceeds the budget, the count is `0` and a disclosure says so.

## Implementation

- **Config** — `OptionsRecommendationConfig` (immutable, validated);
  `config/options_recommendation.example.yaml`.
- **Types** — frozen dataclasses (`RecommendationInputs`, `ContractRecommendation`,
  `StructureCandidate`, `AvoidGate`, `OptionsRecommendation`) with `to_dict`.
- **Pricing** — `options_recommendation/pricing.py`, pure approximation helpers.
- **Engine** — `options_recommendation/engine.py`, a pure
  `RecommendationInputs → OptionsRecommendation`.
- **Service** — `api/options_recommendation_service.py` assembles the inputs from
  the scan (price/ATR/liquidity), the eligibility verdict, the trade-plan holding
  estimate, the dynamic risk budget and account equity. **No persistence** —
  derived on demand.
- **API** — `GET /options-recommendation/{symbol}` (404 without a scan).
- **Tests** — `tests/unit/options_recommendation/` (config, pricing, engine) and an
  endpoint test in `tests/unit/api/test_api.py`.

## No live execution

This engine produces a research recommendation only. It does not connect to a
broker, does not place or simulate orders, and every result carries risk
disclosures (100%-of-premium loss potential, theta decay, approximate pricing,
verify-the-chain). Order routing remains the responsibility of `execution/`.
