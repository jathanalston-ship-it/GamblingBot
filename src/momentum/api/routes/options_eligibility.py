"""Options-eligibility endpoint (read-only — gate only, no contract chosen)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from momentum.api import options_eligibility_service
from momentum.api.dependencies import get_session
from momentum.api.schemas import OptionsEligibilityOut

router = APIRouter(prefix="/options-eligibility", tags=["options-eligibility"])


@router.get("/{symbol}", response_model=OptionsEligibilityOut)
def get_options_eligibility(
    symbol: str,
    run_id: str | None = None,
    session: Session = Depends(get_session),
) -> OptionsEligibilityOut:
    """Shares-Preferred / Leverage-Eligible verdict + per-factor reasons."""
    result = options_eligibility_service.options_eligibility(session, symbol, run_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"no options-eligibility for {symbol.upper()} (needs a scan)"
        )
    return result
