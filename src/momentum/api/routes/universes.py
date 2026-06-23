"""Universe-management endpoints.

List / create / import / select the scanner universe. The selection persists to
``settings.yaml`` and drives "Run Scan"; user universes persist to the
``user_universes`` table.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from momentum.api import universe_service
from momentum.api.dependencies import get_session

router = APIRouter(prefix="/universes", tags=["universes"])


def _provider(request: Request) -> object:
    """The active market-data provider (injected stub in tests, else from settings)."""
    factory = getattr(request.app.state, "provider_factory", None)
    if factory is not None:
        return factory()
    from momentum.api import user_settings

    return user_settings.build_provider()


class UniverseSummary(BaseModel):
    key: str
    label: str
    kind: str
    description: str | None = None
    size: int
    editable: bool


class UniverseListOut(BaseModel):
    selected: str
    universes: list[UniverseSummary]
    sectors: list[str]


class SelectIn(BaseModel):
    key: str


class CustomIn(BaseModel):
    label: str
    symbols: list[str]


class ImportIn(BaseModel):
    label: str
    text: str


class SectorIn(BaseModel):
    sector: str
    base: str = "default"


@router.get("", response_model=UniverseListOut)
def list_universes(session: Session = Depends(get_session)) -> UniverseListOut:
    return UniverseListOut(**universe_service.list_universes(session))


@router.get("/selected")
def get_selected(session: Session = Depends(get_session)) -> dict[str, Any]:
    """The resolved selected universe (key, label, kind, size, sample symbols)."""
    u = universe_service.resolve_selected(session)
    return {
        "key": u.key,
        "label": u.label,
        "kind": u.kind.value,
        "size": u.size,
        "symbols": list(u.symbols[:50]),
    }


@router.put("/selected")
def put_selected(body: SelectIn, session: Session = Depends(get_session)) -> dict[str, str]:
    try:
        key = universe_service.set_selected(session, body.key)
    except universe_service.UniverseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"selected": key}


@router.post("", status_code=201)
def create_custom(body: CustomIn, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        return universe_service.create_custom(session, label=body.label, symbols=body.symbols)
    except universe_service.UniverseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/import", status_code=201)
def import_universe(body: ImportIn, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        return universe_service.import_symbols(session, label=body.label, text=body.text)
    except universe_service.UniverseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sector", status_code=201)
def create_sector(body: SectorIn, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        return universe_service.create_sector(session, sector=body.sector, base_key=body.base)
    except universe_service.UniverseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{key}/refresh")
def refresh_universe(key: str, request: Request) -> dict[str, Any]:
    """Refresh a built-in universe's membership from the data provider (hybrid).

    Returns 400 if the key isn't a refreshable built-in or the provider can't list
    constituents (in which case the shipped seed remains in use).
    """
    try:
        return universe_service.refresh_builtin(_provider(request), key)
    except universe_service.UniverseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{key}")
def delete_universe(key: str, session: Session = Depends(get_session)) -> dict[str, bool]:
    try:
        removed = universe_service.delete_universe(session, key)
    except universe_service.UniverseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail=f"universe not found: {key}")
    return {"deleted": True}
