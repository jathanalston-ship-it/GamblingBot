"""OHLCV bars for charting (cache-first, live fallback).

``GET /bars/{symbol}`` serves the local parquet cache when it covers the
request; on a miss it pulls live from the configured provider once, records
market-data provenance, writes the cache and serves the result — so charts
work immediately after any scan without a separate Refresh Data step.
"""

from __future__ import annotations

import datetime as dt
import os
import time

from fastapi import APIRouter, HTTPException, Request

from momentum.api.schemas import BarOut, BarsOut
from momentum.data.cache import BarCache
from momentum.data.schema import Timeframe

router = APIRouter(prefix="/bars", tags=["bars"])

MAX_DAYS = 730


def _cache() -> BarCache:
    return BarCache(os.environ.get("MRP_BAR_CACHE", "data/bars"))


@router.get("/{symbol}", response_model=BarsOut)
def bars(symbol: str, request: Request, days: int = 180) -> BarsOut:
    """Daily OHLCV for ``symbol`` covering the last ``days`` calendar days."""
    sym = symbol.upper()
    days = max(5, min(days, MAX_DAYS))
    end = dt.date.today()
    start = end - dt.timedelta(days=days)

    cache = _cache()
    frame = None
    source = "cache"
    if cache.exists(sym, Timeframe.DAY):
        frame = cache.read(sym, Timeframe.DAY)

    fresh_enough = (
        frame is not None
        and not frame.empty
        and frame.index[-1].date() >= end - dt.timedelta(days=5)
    )
    if not fresh_enough:
        provider_factory = getattr(request.app.state, "provider_factory", None)
        if provider_factory is not None:
            provider = provider_factory()
        else:
            from momentum.api import user_settings

            provider = user_settings.build_provider()
        started = dt.datetime.now(tz=dt.UTC)
        perf = time.perf_counter()
        try:
            frame = provider.get_bars(sym, start, end, Timeframe.DAY)
            source = "live"
        except Exception as exc:  # noqa: BLE001 — surface the provider failure honestly
            if frame is None or frame.empty:
                raise HTTPException(
                    status_code=502, detail=f"no cached bars and the live pull failed: {exc}"
                ) from exc
            source = "stale-cache"  # keep what we have, labeled
        else:
            if frame is not None and not frame.empty:
                cache.write(sym, Timeframe.DAY, frame)
                _record_provenance(
                    request,
                    symbol=sym,
                    frame_len=len(frame),
                    started=started,
                    duration_ms=round((time.perf_counter() - perf) * 1000.0, 1),
                )

    if frame is None or frame.empty:
        raise HTTPException(status_code=404, detail=f"no bars available for {sym}")

    window = frame[frame.index.date >= start] if len(frame) else frame
    rows = [
        BarOut(
            ts=str(idx.date()),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]) if "volume" in frame.columns else None,
        )
        for idx, row in window.iterrows()
    ]
    return BarsOut(symbol=sym, source=source, bars=rows)


def _record_provenance(
    request: Request, *, symbol: str, frame_len: int, started: dt.datetime, duration_ms: float
) -> None:
    """Best-effort market-data provenance for the live chart pull."""
    try:
        from momentum.persistence.models.market_data_provenance import MarketDataProvenance

        factory = request.app.state.session_factory
        with factory() as session:
            session.add(
                MarketDataProvenance(
                    run_id=None,
                    symbol=symbol,
                    provider="chart",
                    request_timestamp=started,
                    bar_timestamp=None,
                    bar_count=frame_len,
                    request_duration_ms=duration_ms,
                    cache_hit=False,
                    error=None,
                )
            )
            session.commit()
    except Exception:  # noqa: BLE001 — provenance must never break the chart
        pass
