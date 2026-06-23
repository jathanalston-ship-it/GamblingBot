"""Production Data Mode — guarantee scans never display seeded (demo) data.

The platform ships a demo seeder (:mod:`momentum.demo`) that writes sample rows
tagged ``run_id="demo"`` (and ``model_version="demo"`` for market regimes, which
has no ``run_id``). In **demo mode** those rows populate every screen. In
**production mode** they must be invisible — and a fresh install must never mix
seeded data into a live scan.

This module enforces that with **one unbypassable rule**, not 12 hand-patched
queries: a global SQLAlchemy ``do_orm_execute`` listener that, whenever production
mode is active, appends ``with_loader_criteria`` to **every** ORM ``SELECT`` so
demo-tagged rows are filtered out of every read — services, repositories, the
command center, watchlists, everything. Switching to production also **purges**
the demo rows outright. A caller that genuinely needs demo rows (the seeder, the
purge's own accounting) opts out per-statement with
``execution_options(include_demo=True)``.

Default mode is ``demo`` so existing behaviour (and the test suite) is unchanged
until production mode is explicitly selected.
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import CursorResult, delete, event, func, select
from sqlalchemy.orm import Session, with_loader_criteria

from momentum.api import user_settings
from momentum.persistence.models import MarketRegime
from momentum.persistence.models.base import Base

DEMO_RUN_ID = "demo"
DEMO_MODEL_VERSION = "demo"
PRODUCTION = "production"
DEMO = "demo"

# Per-statement opt-out: include_demo=True bypasses the global demo filter.
INCLUDE_DEMO = "include_demo"


# --------------------------------------------------------------------------- #
# Which models carry a demo tag.
# --------------------------------------------------------------------------- #
def _run_id_models() -> list[type[Base]]:
    """Every mapped model that has a ``run_id`` column (demo-taggable)."""
    models: list[type[Base]] = []
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        if "run_id" in mapper.columns:
            models.append(cls)
    return models


_RUN_ID_MODELS = _run_id_models()


# --------------------------------------------------------------------------- #
# Runtime mode flag (cached; refreshed from settings on demand).
# --------------------------------------------------------------------------- #
_production: bool = False


def is_production() -> bool:
    """Whether production data mode is currently active (process flag)."""
    return _production


def demo_allowed() -> bool:
    """Whether demo seeding / demo data is permitted (i.e. not production)."""
    return not _production


def current_mode() -> str:
    return PRODUCTION if _production else DEMO


def set_runtime_mode(mode: str) -> None:
    """Set the in-process flag (does not persist). Used at startup + after a write."""
    global _production
    _production = mode == PRODUCTION


def load_from_settings() -> str:
    """Load the persisted mode into the process flag (call at app startup)."""
    mode = user_settings.read_data_mode()
    set_runtime_mode(mode)
    return mode


# --------------------------------------------------------------------------- #
# The global demo-exclusion filter (registered once, gated by the flag).
# --------------------------------------------------------------------------- #
@event.listens_for(Session, "do_orm_execute")
def _exclude_demo_rows(execute_state: object) -> None:
    """Append demo-excluding criteria to every ORM SELECT in production mode."""
    state = execute_state  # typed loosely; SQLAlchemy ORMExecuteState
    if not _production:
        return
    if not getattr(state, "is_select", False):
        return
    if getattr(state, "execution_options", {}).get(INCLUDE_DEMO, False):
        return
    options = [
        with_loader_criteria(
            model,
            lambda cls: cls.run_id.is_distinct_from(DEMO_RUN_ID),
            include_aliases=True,
        )
        for model in _RUN_ID_MODELS
    ]
    # market_regimes has no run_id; demo rows are tagged via model_version.
    options.append(
        with_loader_criteria(
            MarketRegime,
            MarketRegime.model_version.is_distinct_from(DEMO_MODEL_VERSION),
            include_aliases=True,
        )
    )
    state.statement = state.statement.options(*options)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# Purge demo rows (when switching to production).
# --------------------------------------------------------------------------- #
def count_demo_rows(session: Session) -> int:
    """Total demo-tagged rows currently in the database."""
    total = 0
    for model in _RUN_ID_MODELS:
        stmt = (
            select(func.count())
            .select_from(model)
            .where(model.run_id == DEMO_RUN_ID)  # type: ignore[attr-defined]
            .execution_options(**{INCLUDE_DEMO: True})
        )
        total += int(session.scalar(stmt) or 0)
    stmt = (
        select(func.count())
        .select_from(MarketRegime)
        .where(MarketRegime.model_version == DEMO_MODEL_VERSION)
        .execution_options(**{INCLUDE_DEMO: True})
    )
    total += int(session.scalar(stmt) or 0)
    return total


def purge_demo_rows(session: Session) -> dict[str, int]:
    """Delete every demo-tagged row. Returns ``{table: rows_deleted}``."""
    deleted: dict[str, int] = {}
    for model in _RUN_ID_MODELS:
        result = cast(
            "CursorResult[Any]",
            session.execute(
                delete(model)
                .where(model.run_id == DEMO_RUN_ID)  # type: ignore[attr-defined]
                .execution_options(**{INCLUDE_DEMO: True})
            ),
        )
        if result.rowcount:
            deleted[model.__tablename__] = int(result.rowcount)
    regime_result = cast(
        "CursorResult[Any]",
        session.execute(
            delete(MarketRegime)
            .where(MarketRegime.model_version == DEMO_MODEL_VERSION)
            .execution_options(**{INCLUDE_DEMO: True})
        ),
    )
    if regime_result.rowcount:
        deleted[MarketRegime.__tablename__] = int(regime_result.rowcount)
    return deleted


# --------------------------------------------------------------------------- #
# Public mode-switch operation.
# --------------------------------------------------------------------------- #
def set_mode(session: Session, mode: str) -> dict[str, object]:
    """Persist + activate a data mode. Switching to production purges demo rows.

    Returns a summary: the new mode and (for production) what was purged.
    """
    if mode not in user_settings.VALID_DATA_MODES:
        raise ValueError(f"unknown data mode: {mode}")
    user_settings.write_data_mode(mode)
    set_runtime_mode(mode)
    purged: dict[str, int] = {}
    if mode == PRODUCTION:
        purged = purge_demo_rows(session)
        session.commit()
    return {"mode": mode, "purged": purged, "purged_total": sum(purged.values())}
