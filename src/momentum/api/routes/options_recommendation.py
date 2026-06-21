"""Options-recommendation endpoint (read-only — recommends a contract, never trades)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from momentum.api import options_recommendation_service
from momentum.api.dependencies import get_session
from momentum.api.schemas import OptionsRecommendationOut

router = APIRouter(prefix="/options-recommendation", tags=["options-recommendation"])


@router.get("/{symbol}", response_model=OptionsRecommendationOut)
def get_options_recommendation(
    symbol: str,
    run_id: str | None = None,
    session: Session = Depends(get_session),
) -> OptionsRecommendationOut:
    """A defined-risk options contract (expiration/strike/delta/risk/max-loss/target)."""
    result = options_recommendation_service.options_recommendation(session, symbol, run_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"no options recommendation for {symbol.upper()} (needs a scan)",
        )
    return result
