"""Bar data access.

By design, bars live in the parquet cache (:class:`momentum.data.cache.BarCache`),
not in SQLite — there is no bars repository. ``GET /bars/{symbol}`` serves the
cache with a live-pull fallback (:mod:`momentum.api.routes.bars`).
"""
