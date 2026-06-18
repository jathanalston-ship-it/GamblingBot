"""Abstract MarketDataProvider interface.

Decouples the platform from any single vendor. Contract: get_bars(symbols, start,
end, timeframe) -> bars; get_corporate_actions(...); list_symbols(...).
All concrete adapters are interchangeable.

Architecture scaffold only — interface contract described below; NO implementation yet.
See docs/ARCHITECTURE.md for the full module catalog and diagrams.
"""
