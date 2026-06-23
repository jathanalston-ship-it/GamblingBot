"""Service layer for universe management: list, resolve, create, select.

Bridges the built-in universe registry (:mod:`momentum.universe.universes`) and
the persisted user universes (``user_universes`` table). The scan path calls
:func:`resolve_selected` to get the symbols + sector map for the user's chosen
universe; the Settings UI uses the rest to list/create/import/select universes.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from momentum.api import user_settings
from momentum.persistence.repositories.user_universes import UserUniverseRepository
from momentum.universe.universes import (
    BUILTIN_DEFS,
    DEFAULT_UNIVERSE_KEY,
    ResolvedUniverse,
    UniverseKind,
    builtin_symbols,
    is_builtin,
    known_sectors,
    parse_symbols,
    provider_symbols,
    resolve_builtin,
    sectors_for,
    write_builtin_override,
)


class UniverseError(ValueError):
    """A bad universe request (unknown key, empty list, built-in mutation)."""


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "universe"


def _unique_key(session: Session, base: str) -> str:
    """A key not used by a built-in or an existing user universe."""
    repo = UserUniverseRepository(session)
    candidate = base
    n = 2
    taken = is_builtin(candidate) or repo.by_key(candidate) is not None
    while taken:
        candidate = f"{base}-{n}"
        n += 1
        taken = is_builtin(candidate) or repo.by_key(candidate) is not None
    return candidate


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
def list_universes(session: Session) -> dict[str, Any]:
    """All selectable universes (built-in + user) with sizes + the selection."""
    builtins = [
        {
            "key": d.key,
            "label": d.label,
            "kind": d.kind.value,
            "description": d.description,
            "size": len(builtin_symbols(d.key)),
            "editable": False,
        }
        for d in BUILTIN_DEFS
    ]
    users = [
        {
            "key": u.key,
            "label": u.label,
            "kind": u.kind,
            "description": u.description,
            "size": u.size,
            "editable": True,
        }
        for u in UserUniverseRepository(session).all_ordered()
    ]
    universes = builtins + users
    selected = user_settings.read_selected_universe()
    if selected not in {u["key"] for u in universes}:
        selected = DEFAULT_UNIVERSE_KEY
    return {"selected": selected, "universes": universes, "sectors": known_sectors()}


def resolve(session: Session, key: str) -> ResolvedUniverse:
    """Resolve a universe by key (built-in via registry, else the DB)."""
    if is_builtin(key):
        return resolve_builtin(key)
    row = UserUniverseRepository(session).by_key(key)
    if row is None:
        raise UniverseError(f"unknown universe: {key}")
    symbols = tuple(row.symbols or [])
    sectors = dict(row.sectors or {}) or sectors_for(symbols)
    return ResolvedUniverse(
        key=row.key,
        label=row.label,
        kind=UniverseKind(row.kind),
        symbols=symbols,
        sectors=sectors,
    )


def resolve_selected(session: Session) -> ResolvedUniverse:
    """Resolve the user's selected universe, falling back to the default."""
    key = user_settings.read_selected_universe()
    try:
        return resolve(session, key)
    except UniverseError:
        return resolve_builtin(DEFAULT_UNIVERSE_KEY)


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #
def set_selected(session: Session, key: str) -> str:
    """Persist the selected universe (must exist as built-in or user universe)."""
    if not is_builtin(key) and UserUniverseRepository(session).by_key(key) is None:
        raise UniverseError(f"unknown universe: {key}")
    return user_settings.write_selected_universe(key)


def create_custom(
    session: Session,
    *,
    label: str,
    symbols: list[str],
    kind: UniverseKind = UniverseKind.CUSTOM,
    description: str | None = None,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a user universe from an explicit symbol list."""
    cleaned = parse_symbols(" ".join(symbols))
    if not cleaned:
        raise UniverseError("a universe must contain at least one valid symbol")
    label = label.strip() or "Custom Universe"
    repo = UserUniverseRepository(session)
    key = _unique_key(session, _slug(label))
    row = repo.upsert(
        key=key,
        label=label,
        kind=kind.value,
        symbols=cleaned,
        description=description,
        sectors=sectors_for(cleaned) or None,
        source=source,
    )
    session.commit()
    return row.to_dict()


def import_symbols(session: Session, *, label: str, text: str) -> dict[str, Any]:
    """Create a user universe by parsing a free-form pasted/imported symbol list."""
    symbols = parse_symbols(text)
    if not symbols:
        raise UniverseError("no valid symbols found in the imported list")
    return create_custom(
        session,
        label=label,
        symbols=symbols,
        kind=UniverseKind.IMPORTED,
        description=f"Imported list ({len(symbols)} symbols).",
        source={"imported": True},
    )


def create_sector(
    session: Session, *, sector: str, base_key: str = DEFAULT_UNIVERSE_KEY
) -> dict[str, Any]:
    """Create a sector universe: a base universe filtered to one GICS sector."""
    base = resolve(session, base_key)
    symbols = [s for s in base.symbols if base.sectors.get(s) == sector]
    if not symbols:
        raise UniverseError(f"no symbols in sector {sector!r} for base {base_key!r}")
    return create_custom(
        session,
        label=f"{sector} (Sector)",
        symbols=symbols,
        kind=UniverseKind.SECTOR,
        description=f"{sector} members of {base.label}.",
        source={"base": base_key, "sector": sector},
    )


def refresh_builtin(provider: object, key: str) -> dict[str, Any]:
    """Refresh a built-in universe's membership from the data provider (hybrid).

    Shipped seeds remain the default; this updates the persisted override when the
    active provider can enumerate constituents. Raises ``UniverseError`` for a
    non-refreshable key or a provider without listing support.
    """
    if not is_builtin(key) or key == DEFAULT_UNIVERSE_KEY:
        raise UniverseError(f"not a refreshable built-in universe: {key}")
    symbols = provider_symbols(provider, key)
    if symbols is None:
        raise UniverseError(
            "the active data provider does not support live universe refresh; "
            "the shipped seed list is in use"
        )
    size = write_builtin_override(key, symbols)
    return {"key": key, "size": size, "refreshed": True}


def delete_universe(session: Session, key: str) -> bool:
    """Delete a user universe (built-ins cannot be deleted)."""
    if is_builtin(key):
        raise UniverseError(f"cannot delete a built-in universe: {key}")
    removed = UserUniverseRepository(session).delete_by_key(key)
    if removed and user_settings.read_selected_universe() == key:
        user_settings.write_selected_universe(DEFAULT_UNIVERSE_KEY)
    session.commit()
    return removed
