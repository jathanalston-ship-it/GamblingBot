# UX Interaction Audit — every button accounted for

Rule under audit: **no button may ever appear ignored.** Every control
that performs work longer than ~100 ms must give an immediate visual
response, a loading state, progress where available, and a
completion/error state.

## Interaction patterns in the app

| Pattern | Where | Feedback provided |
| --- | --- | --- |
| **ActionButton + background job** | Run Scan, Backtest, Walk-forward, Paper Session, Refresh Data, Seed Demo, Generate Watchlists, Refresh Lifecycles, Reevaluate, Track WL Performance | Click → button disables instantly, label switches, a job is created and its **live progress fraction + message** poll into the button; success/failure lands as a completion state with the result or error text |
| **Busy-flag mutators** | Settings saves (provider/keys/data mode/autopilot/shadow/execution/notifications/universes/profiles), Brokerage order form/cancel/close, Trade Plan take/track dialogs, TradeActions, DiagnosticsPanel clear, ResetPanel | Click → `busy` state disables the control and swaps the label ("Saving…", "Placing…", "Working…"); success/error messages render inline; destructive paths are confirm-gated first |
| **Optimistic toggles** | Shadow mode checkbox, notification mutes, prevent-sleep | Disable-while-saving + reload on completion; errors surface inline |
| **Updater** | Check / Download / Restart & install | Check and Download disable + show progress percent; **Restart & install now flips to a spinner ("Restarting…") on the same click and hands off to the full-screen Update overlay** (fixed in this audit — it previously gave no feedback at all) |
| **Daemon controls** | Command Center LivePulse Pause/Resume/Scan now | **Fixed in this audit**: per-button busy labels ("Pausing…", "Resuming…", "Requesting…") instead of a silent shared disable |

## Sweep results (every component that mutates)

| Surface | Buttons | Immediate response | Loading state | Success/error state | Verdict |
| --- | --- | --- | --- | --- | --- |
| Settings (9 panels) | save/toggle/import/delete | disable + label swap | yes | inline msg / ErrorBox | OK |
| Updates | check / download / install | disable; download % | yes | status line; overlay | **fixed** (install) |
| Brokerage | place/cancel/modify/close | disable + busy | yes | inline verdicts | OK |
| Trade Plan / TradeActions | take / track / close | disable + busy | yes | dialog result / error | OK |
| Command Center LivePulse | pause/resume/scan-now | disable | **added labels** | status refresh | **fixed** |
| Verification | verify pipeline | disable | "Running…" | PASS/FAIL table | OK |
| Replay / Timeline | play/step/jump | instant local state | n/a (<100 ms) | n/a | OK |
| ResetPanel | reset / reset+demo | confirm gate + busy | yes | relaunch/error | OK |
| DiagnosticsPanel | refresh/clear | disable + label | yes | list refresh | OK |
| Watchlists / WL Perf / Scanner | generate/track/scan | ActionButton jobs | live progress | job result | OK |

Read-only navigation (tabs, filters, row expanders, chart hovers) is
local state and renders in the same frame; excluded from the table.

## Fixes applied in this audit

1. **Restart & install** — immediate spinner + all-controls disable +
   full-screen UpdateOverlay with step checklist, elapsed time, 5-second
   reassurance and a failure recovery dialog (previously: zero feedback,
   then a silently-dying window).
2. **LivePulse daemon buttons** — per-button busy labels.
3. **Single-instance lock wait** — a splash window during the up-to-9 s
   relaunch collision (previously: no window at all).

Everything else already followed the ActionButton/busy-flag patterns;
the completion/error animations are the inline state transitions those
patterns render (label swap + colored status text), kept deliberately
quiet to match the app's design language.
