"""Persistence: SQLAlchemy models, repositories, append-only audit log, migrations.

SQLite (WAL mode) for research; the repository pattern keeps SQL out of business
logic and allows swapping to Postgres for production without touching callers.
See docs/ARCHITECTURE.md for the full module catalog and diagrams.
"""
