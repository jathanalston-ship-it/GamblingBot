"""Self-audit of the API surface: live-probe every route and classify it.

Enumerates the app's own routes and issues a real in-process request to each GET
route (through the full middleware + DB stack via an ASGI transport — no network),
classifying the result as PASS / 404 / 500 / FAIL / TIMEOUT. Mutating routes
(POST/PUT/DELETE) and the audit route itself are SKIPPED so the probe has no side
effects. This is what powers ``GET /health/routes`` — broken routes surface
automatically.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re

import httpx
from fastapi import FastAPI

from momentum.api.schemas import ApiHealthReportOut, RouteHealthOut

# Sample path-parameter values so a templated route resolves to a real URL.
_PATH_SAMPLES = {
    "symbol": "AAPL",
    "horizon": "daily",
    "name": "strategy",
    "job_id": "__healthcheck__",
}
# Query params supplied to every probe (extras are ignored by handlers that don't
# use them; these satisfy the few routes with required query params).
_DEFAULT_PARAMS: dict[str, str | int] = {
    "symbol": "AAPL",
    "horizon": "daily",
    "base": "2000-01-01",
    "against": "2000-01-02",
    "limit": 5,
    "a": 1,  # /timeline/diff snapshot ids (missing ids → a healthy 404)
    "b": 2,
}
_SELF_PATH = "/health/routes"
# GET routes with external side effects (live provider pulls) — probing them
# would issue a real network request and grade the app on vendor availability.
_EXTERNAL_FETCH_PATHS = {"/bars/{symbol}"}


def _fill(path: str) -> str:
    """Resolve ``/tradeplan/{symbol}`` → ``/tradeplan/AAPL`` from the samples."""
    return re.sub(r"\{([^}]+)\}", lambda m: _PATH_SAMPLES.get(m.group(1).split(":")[0], "0"), path)


def _classify(status: int) -> str:
    if status == 404:
        return "404"
    if status >= 500:
        return "500"
    if status >= 400:
        return "FAIL"
    return "PASS"


def _detail(resp: httpx.Response) -> str | None:
    try:
        body = resp.json()
        if isinstance(body, dict) and body.get("detail"):
            return str(body["detail"])[:300]
    except ValueError:
        pass
    return resp.text[:300] or None


def _enumerate(app: FastAPI) -> list[tuple[str, str]]:
    """Every (METHOD, path) the app publishes — from its own OpenAPI schema."""
    paths: dict[str, dict[str, object]] = app.openapi().get("paths", {})
    out: list[tuple[str, str]] = []
    for path, operations in sorted(paths.items()):
        for method in operations:
            if method.upper() in {"HEAD", "OPTIONS", "TRACE"}:
                continue
            out.append((method.upper(), path))
    return out


async def audit_routes(app: FastAPI, *, timeout: float = 15.0) -> ApiHealthReportOut:
    """Probe every GET route in ``app`` and return a classified health report."""
    results: list[RouteHealthOut] = []

    # raise_app_exceptions=False: a probed route that 500s should come back as a
    # 500 *response* (via the app's exception handler) to be classified, not
    # re-raised into the audit loop.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://api-health") as client:
        for method, path in _enumerate(app):
            if path == _SELF_PATH:
                results.append(
                    RouteHealthOut(
                        method=method,
                        path=path,
                        classification="SKIPPED",
                        http_status=None,
                        detail="the audit route itself",
                    )
                )
                continue
            if method != "GET":
                results.append(
                    RouteHealthOut(
                        method=method,
                        path=path,
                        classification="SKIPPED",
                        http_status=None,
                        detail="mutating route — not probed",
                    )
                )
                continue
            if path in _EXTERNAL_FETCH_PATHS:
                results.append(
                    RouteHealthOut(
                        method="GET",
                        path=path,
                        classification="SKIPPED",
                        http_status=None,
                        detail="live market-data fetch — not probed",
                    )
                )
                continue

            try:
                resp = await asyncio.wait_for(
                    client.get(_fill(path), params=_DEFAULT_PARAMS), timeout=timeout
                )
            except TimeoutError:
                results.append(
                    RouteHealthOut(
                        method="GET",
                        path=path,
                        classification="TIMEOUT",
                        http_status=None,
                        detail=f"no response in {timeout:.0f}s",
                    )
                )
                continue
            except Exception as exc:  # noqa: BLE001 - probe must never abort the audit
                results.append(
                    RouteHealthOut(
                        method="GET",
                        path=path,
                        classification="FAIL",
                        http_status=None,
                        detail=f"{type(exc).__name__}: {exc}"[:300],
                    )
                )
                continue

            cls = _classify(resp.status_code)
            results.append(
                RouteHealthOut(
                    method="GET",
                    path=path,
                    classification=cls,
                    http_status=resp.status_code,
                    detail=_detail(resp) if cls in ("500", "FAIL") else None,
                )
            )

    def n(c: str) -> int:
        return sum(1 for r in results if r.classification == c)

    server_errors, failed, timeouts = n("500"), n("FAIL"), n("TIMEOUT")
    return ApiHealthReportOut(
        total=len(results),
        passed=n("PASS"),
        not_found=n("404"),
        server_errors=server_errors,
        failed=failed,
        timeouts=timeouts,
        skipped=n("SKIPPED"),
        healthy=(server_errors == 0 and failed == 0 and timeouts == 0),
        routes=results,
        generated_at=dt.datetime.now(tz=dt.UTC).isoformat(),
    )
