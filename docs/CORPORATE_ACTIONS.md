# Corporate-Actions Provider

The dedicated, provider-agnostic seam for **event** data (as opposed to bars):
when does a symbol report earnings next, when does it trade ex-dividend, and
how much does it pay?

## Design

- **Pure value object** — `CorporateCalendar`
  (`src/momentum/data/corporate_calendar.py`): symbol, as_of, earnings date,
  ex-dividend date, dividend payment date, annualized dividend amount, source;
  derived `days_until_earnings` / `days_until_ex_dividend`; `to_dict()`.
  Every field is `None` when honestly unknown.
- **Protocol** — `CorporateActionsProvider` (`name` + `calendar(symbol)`).
  Implementations:
  - `YahooCorporateActions` — Yahoo `quoteSummary`
    (`calendarEvents,summaryDetail`), keyless, `httpx.MockTransport`-testable.
    Past earnings dates never count as "next"; ex-div prefers calendarEvents
    and falls back to summaryDetail.
  - `NullCorporateActions` — always unknown (offline/test default).
- **Advisory semantics** — any failure (HTTP error, empty payload, parse
  error) degrades to `unknown_calendar(symbol)`; the calendar can never break
  a take-trade gate or a plan view.
- **Service** — `api/corporate_actions_service.py`: thread-safe 6-hour TTL
  cache per symbol, `calendar()` / `days_until_earnings()` /
  `days_until_ex_dividend()` / `clear_cache()`. The earnings-only façade
  (`api/earnings_service.py`) delegates here, so the take-trade gate and the
  `/earnings` route share the same cache.

## API

- `GET /earnings/{symbol}` → `EarningsOut` (unchanged contract).
- `GET /corporate-actions/{symbol}` → `CorporateActionsOut` (full calendar:
  earnings + ex-div + payment date + amount + source).

## Consumers

- **Take-trade gate** — `block_take_days_before_earnings`
  (`config/trade_lifecycle.example.yaml`) blocks opening right before a
  report.
- **Trade Plan chips** — amber "Earnings in Nd" (≤ 14 days) and sky
  "Ex-div in Nd" (≤ 7 days, with the annualized amount in the tooltip).

## Swapping in a real vendor

Implement `CorporateActionsProvider` for the vendor and return it from
`default_provider()` (or inject per call). Everything upstream — cache,
gates, routes, chips — is unchanged.

## Tests

`tests/unit/data/test_corporate_calendar.py` (MockTransport parse/degrade
paths, protocol conformance) and
`tests/unit/api/test_corporate_actions_service.py` (cache behaviour, error
degradation, façade delegation).
