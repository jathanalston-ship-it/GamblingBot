# Setup Lifecycle Tracking

Every candidate exists in exactly **one** state, derived automatically from its
evidence and tracked over time:

```
Building → Ready → Triggered → Active → Extended        ┌ Completed
   (setup forming)  (nearly)  (entry)  (in trade) (crowded) └ Failed
```

| State | Meaning | Derived when |
|---|---|---|
| **Building** | setup forming | scanned but not yet near the trigger (the default) |
| **Ready** | conditions nearly met | passed scan + conviction ≥ threshold + near the ATH + volume building |
| **Triggered** | entry condition hit | an entry signal exists, or price broke out to/through the high |
| **Active** | trade in progress | an open position exists |
| **Extended** | move has become crowded | open position up ≥ `extended_r` / `extended_gain_pct`, or climax volume at the highs |
| **Failed** | setup invalidated | a closed losing trade, or a Ready/Triggered setup that lost its gating / support |
| **Completed** | target reached | a closed trade that hit target / finished positive |

The mapping is a **priority cascade** (closed trade → terminal; open trade →
Active/Extended; otherwise the pre-trade state from scan + conviction, with an
invalidation path to Failed). Thresholds are tunable in
`config/lifecycle.example.yaml`.

## Persistence + automatic transitions

One row per `(run_id, symbol)` in `setup_lifecycles` (migration `0012`) holds the
**current state**, `previous_state`, `state_since`, the reason, and a JSON
**transition history**. `SetupLifecycleRepository.upsert` re-derives the state and
**appends a transition only when it changes** — so transitions are generated
automatically, never entered by hand.

`refresh_lifecycles` (`api/lifecycle_service.py`) assembles each candidate's
evidence from the persisted scan / conviction / entry signals / trades, runs the
pure `LifecycleEngine`, and upserts. It runs:

- automatically as the **final step of every daily session**
  (`DailyOrchestrationEngine`, toggle `track_lifecycles`),
- on demand via `POST /actions/refresh-lifecycles`,
- and the demo seeds a full spread across all seven states.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/lifecycles?run_id=&state=` | Every candidate's state (filter by `state`). |
| `GET` | `/lifecycles/summary` | Per-state counts for the pipeline view. |
| `GET` | `/lifecycles/{symbol}` | One candidate's state + transition history. |
| `POST` | `/actions/refresh-lifecycles` | Re-derive + persist all states. |

## Desktop

The **Lifecycle** view (left rail) shows the pipeline as clickable, counted state
chips (`Building → … → Extended`, then terminal `Completed` / `Failed`), **filters
the table by clicking a state**, and expands each row to its **transition
history**. A **Refresh** button re-derives states on demand.
