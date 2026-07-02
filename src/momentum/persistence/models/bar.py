"""OHLCV bars table.

By design, bars are not stored in SQLite: the bar store is one
snappy-parquet file per symbol+timeframe (:mod:`momentum.data.cache`), which
is both smaller and faster for columnar reads.
"""
