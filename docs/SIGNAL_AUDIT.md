# Signal Validation Audit

Are the platform's predictions actually predictive? The audit takes the **last N
candidates that produced an outcome** (closed trades joined to their prediction
context) and grades every predictive surface against realised results — then only
recommends changes **where a statistical test is significant**. With no significant
signal it says so; it does not invent conclusions.

## What it measures

For each candidate it joins the prediction (conviction + sub-factors, best watchlist
rank, options-eligibility verdict + confidence, options-recommendation verdict) to
the realised trade outcome (R-multiple, MFE, MAE, exit reason) and evaluates the six
surfaces:

| Surface | How it's judged |
|---|---|
| **Conviction** | Pearson IC of conviction vs realised R (+ calibration) |
| **Watchlist ranking** | IC of (better) rank vs realised R |
| **Trade-plan targets** | % reaching the target tier (MFE ≥ `target_r`); % exiting at target |
| **Stop losses** | avg loser R; % overrunning past `stop_overrun_r` |
| **Options recommendation** | Welch t-test of R for recommended vs not |
| **Eligibility gate** | Welch t-test of R for eligible vs shares-preferred |

## What it generates

- **Win rate by conviction bucket** and **expected value (R) by conviction bucket**.
- **Maximum drawdown** of the candidate outcome sequence (in R).
- **Average reward:risk** (avg MFE / |MAE|) and payoff ratio.
- **Calibration report** — predicted (conviction) vs actual win rate per bucket,
  Brier score, monotonicity, conviction IC + p-value.
- **Strongest predictive factors** — significant factors ranked by |IC|.
- **Weakest predictive factors** — factors with the least demonstrated edge (reported
  as "no demonstrated edge", *not* as proven useless — absence of evidence ≠ evidence
  of absence).
- **Recommendations** — emitted **only** when a test is significant at `alpha` with a
  sufficient sample (`min_sample` for correlations, `min_group` per group for t-tests).
  When nothing is significant the audit states that explicitly.

## Significance, honestly

`analytics/significance.py` provides the inferential statistics with no scipy
dependency: Pearson correlation with a two-sided p-value (Student-t via the
regularized incomplete beta), Welch's two-sample t-test, a two-proportion z-test
(normal tail via `erfc`) and a peak-to-trough drawdown. A finding is only called
significant when `p < alpha` **and** the sample clears the minimum-n threshold.

## Implementation

- **Config** — `SignalAuditConfig` (lookback, alpha, min samples, target/stop tiers,
  buckets); `config/signal_audit.example.yaml`.
- **Types** — frozen dataclasses (`CandidateOutcome`, `ConvictionBucketStat`,
  `FactorScore`, `CalibrationReport`, `AreaEffectiveness`, `SignalAuditReport`).
- **Engine** — `signal_audit/engine.py`, pure `audit(candidates, cfg) -> report`.
- **Significance** — `analytics/significance.py` (shared, pure).
- **Service** — `api/signal_audit_service.py` assembles the last N candidates from the
  DB (trades + conviction + watchlist + scan-derived eligibility/recommendation).
  **Read-only, no persistence.**
- **API** — `GET /signal-audit[?run_id=&limit=]`.
- **Desktop** — a **Signal Audit** view: headline metrics, the
  significance-gated recommendations, win-rate/EV by bucket + calibration, the ranked
  predictive factors, per-subsystem effectiveness, weakest factors, and caveats.

## Caveats (always reported)

- Only candidates that **produced a closed trade** are audited (survivorship).
- Outcome is realised **trade R**; options-structure P&L is proxied by the underlying
  result, not contract pricing.
- Prediction context is joined **by symbol to the latest generation**, not strictly
  point-in-time at entry.
- Below `min_sample`, every finding is flagged indicative-only.
