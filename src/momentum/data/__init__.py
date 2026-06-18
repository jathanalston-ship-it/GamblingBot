"""Market-data layer: acquisition, adjustment, validation, caching, persistence.

Produces clean, point-in-time-correct, split/dividend-adjusted OHLCV series that
the rest of the platform can trust. Everything flows through one canonical
DataFrame contract (:mod:`momentum.data.schema`), so the three vendors — Alpaca,
Polygon and Yahoo — are fully interchangeable behind
:class:`~momentum.data.providers.base.MarketDataProvider`.

Typical use::

    from momentum.data import AlpacaProvider, BarCache, DataIngestor, Timeframe

    ingestor = DataIngestor(AlpacaProvider(), BarCache("data/cache"))
    bars = ingestor.load("AAPL", "2020-01-01", "2023-12-31", Timeframe.DAY)

See docs/ARCHITECTURE.md for the full module catalog and diagrams.
"""

from __future__ import annotations

from momentum.data.cache import BarCache
from momentum.data.calendar import TradingCalendar
from momentum.data.ingestion import DataIngestor, IngestionResult
from momentum.data.providers.alpaca import AlpacaProvider
from momentum.data.providers.base import MarketDataProvider, RestProvider
from momentum.data.providers.polygon import PolygonProvider
from momentum.data.providers.yfinance import YahooProvider
from momentum.data.schema import (
    Adjustment,
    DataRequest,
    Timeframe,
    empty_bars,
    normalize_bars,
)
from momentum.data.validation import BarQualityReport, validate_bars

__all__ = [
    # schema
    "Adjustment",
    "DataRequest",
    "Timeframe",
    "empty_bars",
    "normalize_bars",
    # providers
    "MarketDataProvider",
    "RestProvider",
    "AlpacaProvider",
    "PolygonProvider",
    "YahooProvider",
    # cache / calendar
    "BarCache",
    "TradingCalendar",
    # ingestion
    "DataIngestor",
    "IngestionResult",
    # validation
    "BarQualityReport",
    "validate_bars",
]
