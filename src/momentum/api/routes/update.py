"""Local self-update endpoints — expose ``mrp update`` / ``rollback`` to the UI.

So a non-technical user can update from inside the desktop app (no terminal),
the renderer calls these. They wrap the git-based :class:`~momentum.update.Updater`.

On a **packaged** build (a frozen binary with no git repository) updating in
place is not possible — those endpoints report ``supported = false`` with a note
that the build updates by installing a newer download. The updater is built via
``app.state.updater_factory`` when present, so tests can inject a stub (offline).
"""

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request

from momentum.api.schemas import RollbackResultOut, UpdateResultOut, UpdateStatusOut
from momentum.core.exceptions import UpdateError

if TYPE_CHECKING:
    from momentum.update.updater import Updater

router = APIRouter(prefix="/update", tags=["update"])


def _is_packaged() -> bool:
    """True when running as a frozen (PyInstaller) binary — no git working copy."""
    return bool(getattr(sys, "frozen", False))


def _installed_version() -> str | None:
    try:
        return pkg_version("momentum-research-platform")
    except PackageNotFoundError:
        return None


def _make_updater(request: Request) -> Updater:
    factory = getattr(request.app.state, "updater_factory", None)
    if factory is not None:
        updater: Updater = factory()
        return updater
    from momentum.update.updater import Updater as _Updater

    return _Updater()


@router.get("/status", response_model=UpdateStatusOut)
def update_status(request: Request) -> UpdateStatusOut:
    """Report whether an update is supported here and whether one is available."""
    if _is_packaged():
        return UpdateStatusOut(
            supported=False,
            update_available=False,
            current_version=_installed_version(),
            reason="This installed build updates by downloading and running a newer installer.",
        )
    try:
        status = _make_updater(request).check()
    except Exception as exc:  # noqa: BLE001 - report, never 500 a status check
        return UpdateStatusOut(
            supported=False,
            update_available=False,
            current_version=_installed_version(),
            reason=f"Updates are unavailable here: {exc}",
        )
    return UpdateStatusOut(
        supported=True,
        update_available=status.update_available,
        current_version=status.current_version,
        remote_version=status.remote_version,
        branch=status.branch,
        behind_by=status.behind_by,
    )


@router.post("/apply", response_model=UpdateResultOut)
def update_apply(request: Request) -> UpdateResultOut:
    """Apply an available update (no auto-restart; the user relaunches the app)."""
    if _is_packaged():
        raise HTTPException(
            status_code=400, detail="Install a newer build to update this packaged app."
        )
    try:
        result = _make_updater(request).update(restart=False)
    except UpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"update failed: {exc}") from exc
    return UpdateResultOut(
        updated=result.updated,
        message=result.message,
        backup_id=result.backup_id,
        from_commit=result.from_commit,
        to_commit=result.to_commit,
    )


@router.post("/rollback", response_model=RollbackResultOut)
def update_rollback(request: Request) -> RollbackResultOut:
    """Roll back to the most recent backup (restores the code commit + database)."""
    try:
        record = _make_updater(request).rollback()
    except UpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RollbackResultOut(
        backup_id=record.backup_id, commit=record.commit, version=record.version
    )
