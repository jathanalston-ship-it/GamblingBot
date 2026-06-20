# Options Eligibility Engine

A read-only **go/no-go gate**: is a setup suitable for options leverage, or should
it be traded as **shares**? It scores six factors into a 0-100 confidence and a
verdict — it never picks a contract (that's the separate
[options-qualification](OPTIONS_QUALIFICATION.md) engine).

## Output

- **Options Eligible:** Yes / No
- **Confidence:** 0-100
- **Recommendation:** `Leverage Eligible` or `Shares Preferred`
- **Reasons** — one assessment (pass / warn / fail + detail) per factor.

## The six factors

| Factor | How it's judged |
|---|---|
| **Liquidity** | average daily dollar volume of the underlying (hard floor) |
| **Volatility** | ATR/price — a sweet spot; too quiet is a hard fail, extreme is a soft warn |
| **Expected Move** | ATR-derived move over the hold — must clear the premium (hard fail) |
| **Time Horizon** | expected holding days — short/medium favours options, long favours shares |
| **Spread Quality** | proxy from price + liquidity (no chain data): higher price + liquidity ⇒ tighter spreads |
| **Market Regime** | directional leverage favours trends (bull > neutral > bear) |

Each factor's score (0-1) is weighted into the confidence. A **hard fail** on
liquidity, volatility or expected move forces `Shares Preferred` regardless of the
confidence. Missing data is treated as a neutral *warn*, never a fail. Thresholds
and weights live in `config/options_eligibility.example.yaml`.

## Implementation

- **Config** — `OptionsEligibilityConfig` (immutable, validated).
- **Engine** — `options_eligibility/engine.py`, a pure
  `EligibilityInputs -> EligibilityResult`.
- **Service** — `api/options_eligibility_service.py` assembles the inputs from the
  scan (price, ATR, liquidity), the trade plan (expected holding period) and the
  market regime. **No persistence** — derived on demand.
- **API** — `GET /options-eligibility/{symbol}` (404 without a scan).
- **Desktop** — an **Options Eligibility** card on the **Trade Plan** view:
  the `Leverage Eligible` / `Shares Preferred` badge, confidence, plain-language
  summary, and the six factors with pass/warn/fail dots.

**No actual option recommendations** — eligibility only.
