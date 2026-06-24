"""Runtime verification endpoints — diagnostics status + a live pipeline check."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from momentum.api import verification_service

router = APIRouter(prefix="/verification", tags=["verification"])


def _provider(request: Request) -> Any:
    factory = getattr(request.app.state, "provider_factory", None)
    if factory is not None:
        return factory()
    from momentum.api import user_settings

    return user_settings.build_provider()


@router.get("/status")
def get_status(request: Request) -> dict[str, Any]:
    """Backend / provider status + latest live run counts + last request timestamps."""
    factory = request.app.state.session_factory
    with factory() as session:
        return verification_service.status(session)


@router.post("/verify-pipeline")
def post_verify_pipeline(request: Request, symbol: str = "AAPL") -> dict[str, Any]:
    """Pull one live symbol and run it through the real engines (PASS/FAIL per stage)."""
    from momentum.api import user_settings

    factory = request.app.state.session_factory
    with factory() as session:
        return verification_service.verify_pipeline(
            session,
            provider=_provider(request),
            symbol=symbol,
            provider_name=user_settings.read_provider(),
        )
