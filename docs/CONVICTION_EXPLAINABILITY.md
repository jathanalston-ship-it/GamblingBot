# Conviction Explainability

Every conviction score now ships with a per-factor explanation: **why** the score
was assigned, which factors helped, which hurt, and a one-line narrative.

## What is stored

The conviction engine already records, for each of the eight factors, a
`ComponentScore` with **factor name · raw value · normalized value · weight ·
contribution** (additive points toward the 0-100 score). These persist in the
`conviction_scores.breakdown` JSON column (migration `0006`) — no new table or
migration was needed (no architecture change).

Factors: market regime · sector strength · relative volume · ATH proximity
(`distance_to_ath`) · trend quality (`trend_strength`) · market breadth ·
momentum · historical analogs (`historical_similar_setups`).

## What the API adds (read time)

`GET /conviction?symbol=…` enriches each score with two computed fields:

- **`contributors`** — a list of `ContributorOut`, one per factor, sorted by
  signed impact (strongest driver first):
  | field | meaning |
  |---|---|
  | `name` / `label` | factor key / human label |
  | `raw` | the raw factor value (e.g. relative volume 2.5) |
  | `weight` | configured weight |
  | `contribution` | additive points toward the score (always ≥ 0) |
  | `impact` | **signed** effect vs a neutral setup — `(normalized − neutral) × weight ÷ Σweight × 100`. Above neutral lifts the score (+), below neutral drags it (−). |
  | `direction` | `"positive"` / `"negative"` |

  `impact` is what makes brakes visible: a factor that scored below neutral (e.g.
  far from its ATH, thin volume) shows as a negative contributor even though every
  raw `contribution` is non-negative. The impacts sum to `score − neutral_baseline`.

- **`narrative`** — a plain-language summary, e.g.
  *"NVDA ranks highly (87/100) due to strong relative volume, market regime and
  historical analogs, partly offset by weak ATH proximity."*

Both are computed in `services._explain` from the stored breakdown; the scoring
model is untouched.

## Frontend (Conviction screen)

- The **narrative** renders as the headline "why" under the score.
- A **Contributors** panel lists each factor with a signed `+`/`−`, label, the
  raw value + weight (muted), a dotted leader and the signed impact (green/red):

  ```
  Conviction · NVDA   87  EXTREME   Tradeable — high conviction

  NVDA ranks highly (87/100) due to strong relative volume, market regime and
  historical analogs, partly offset by weak ATH proximity.

  Contributors                                   impact vs neutral
  + relative volume   (raw 2.50 · w 1.00) ......... +8
  + market regime     (raw 1.00 · w 1.00) ......... +6
  + historical analogs(raw 1.20 · w 1.00) ......... +5
  − ATH proximity     (raw 0.15 · w 1.00) ......... −6
  ```

- The full mechanical breakdown (normalized · weight · contribution + bars) stays
  below for auditing.

See also `docs/CONVICTION.md` (the scoring engine).
