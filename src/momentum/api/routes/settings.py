"""Settings endpoints.

Reading the configuration templates is side-effect free. The data-provider
selection is editable via a small, explicitly-guarded write endpoint
(``PUT /settings/data-provider``) that persists the choice to ``settings.yaml``
and any API-key secrets to ``.env`` (secrets are never read back in plain text).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from momentum.api import data_mode, services, user_settings
from momentum.api.dependencies import get_session
from momentum.api.schemas import ConfigFileOut, DataProviderIn, DataProviderOut

router = APIRouter(prefix="/settings", tags=["settings"])


class DataModeIn(BaseModel):
    mode: str


@router.get("/config", response_model=list[str])
def list_config() -> list[str]:
    """List the available configuration files."""
    return services.list_config_files()


@router.get("/config/{name}", response_model=ConfigFileOut)
def get_config(name: str) -> ConfigFileOut:
    """Read one configuration file (raw text + parsed)."""
    cfg = services.read_config_file(name)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"config file not found: {name}")
    return cfg


def _to_out(settings: user_settings.ProviderSettings) -> DataProviderOut:
    return DataProviderOut(
        provider=settings.provider,
        keys_present=settings.keys_present,
        valid_providers=list(settings.valid_providers),
    )


@router.get("/data-provider", response_model=DataProviderOut)
def get_data_provider() -> DataProviderOut:
    """Current market-data provider + which API keys are set (booleans only)."""
    return _to_out(user_settings.read_provider_settings())


@router.get("/data-mode")
def get_data_mode(session: Session = Depends(get_session)) -> dict[str, Any]:
    """The current data mode (demo/production) + how many demo rows remain."""
    return {
        "mode": data_mode.current_mode(),
        "valid_modes": list(user_settings.VALID_DATA_MODES),
        "demo_rows": data_mode.count_demo_rows(session),
    }


@router.put("/data-mode")
def put_data_mode(body: DataModeIn, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Set the data mode. Switching to production purges all demo-tagged rows."""
    try:
        result = data_mode.set_mode(session, body.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**result, "demo_rows": data_mode.count_demo_rows(session)}


@router.get("/execution-mode")
def get_execution_mode() -> dict[str, Any]:
    """Which venue fills paper orders (internal simulator vs Alpaca paper)."""
    from momentum.api.user_settings import read_provider_settings

    keys = read_provider_settings().keys_present
    return {
        "mode": user_settings.read_execution_mode(),
        "valid_modes": list(user_settings.VALID_EXECUTION_MODES),
        "alpaca_keys_present": bool(keys.get("alpaca_api_key") and keys.get("alpaca_api_secret")),
    }


class ExecutionModeIn(BaseModel):
    mode: str


@router.put("/execution-mode")
def put_execution_mode(body: ExecutionModeIn) -> dict[str, Any]:
    """Set the execution venue (persists to settings.yaml; used by the next session)."""
    try:
        mode = user_settings.write_execution_mode(body.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"mode": mode, "valid_modes": list(user_settings.VALID_EXECUTION_MODES)}


class AutopilotIn(BaseModel):
    enabled: bool | None = None
    starting_balance: float | None = None
    max_open_positions: int | None = None
    max_entries_per_cycle: int | None = None
    min_conviction_score: float | None = None
    include_premarket: bool | None = None
    prevent_sleep: bool | None = None


def _autopilot_out() -> dict[str, Any]:
    return {
        **user_settings.read_autopilot(),
        "starting_balance": user_settings.read_account_balance(),
    }


@router.get("/autopilot")
def get_autopilot() -> dict[str, Any]:
    """Autopilot settings: auto-entry toggle, caps and the account balance."""
    return _autopilot_out()


@router.put("/autopilot")
def put_autopilot(
    body: AutopilotIn, request: Request, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Update autopilot settings + starting balance (partial; persists).

    **Long-Running preflight**: turning autopilot ON runs the automation
    health checks first; a critical subsystem refuses the start (HTTP 409)
    and the response explains every failing subsystem. A changed balance
    re-seeds the brokerage account only while it is still untouched (no
    fills) — a live book's history is never rewritten.
    """
    if body.enabled is True and not user_settings.read_autopilot()["enabled"]:
        from momentum.api import automation_health_service

        failures = automation_health_service.preflight_failures(
            daemon=getattr(request.app.state, "market_daemon", None)
        )
        if failures:
            reasons = "; ".join(f"{f['name']}: {f['detail']}" for f in failures)
            raise HTTPException(
                status_code=409,
                detail=f"Auto Pilot not started — preflight failed: {reasons}",
            )
    try:
        if body.starting_balance is not None:
            user_settings.write_account_balance(body.starting_balance)
            _reseed_untouched_broker_account(session, body.starting_balance)
        user_settings.write_autopilot(
            enabled=body.enabled,
            max_open_positions=body.max_open_positions,
            max_entries_per_cycle=body.max_entries_per_cycle,
            min_conviction_score=body.min_conviction_score,
            include_premarket=body.include_premarket,
            prevent_sleep=body.prevent_sleep,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _autopilot_out()


def _reseed_untouched_broker_account(session: Session, balance: float) -> None:
    from sqlalchemy import func, select

    from momentum.persistence.models.broker import BrokerAccount, BrokerFill

    account = session.scalars(
        select(BrokerAccount).where(BrokerAccount.account_id == "primary")
    ).first()
    if account is None:
        return
    fills = session.scalar(
        select(func.count()).select_from(BrokerFill).where(BrokerFill.account_id == "primary")
    )
    if not fills:
        account.starting_cash = balance
        account.cash = balance
        session.commit()


class NotificationPrefsIn(BaseModel):
    enabled: bool | None = None
    min_severity: str | None = None
    muted_kinds: list[str] | None = None


@router.get("/notifications")
def get_notification_prefs() -> dict[str, Any]:
    """OS-notification preferences (enabled, severity floor, muted alert kinds)."""
    return {
        **user_settings.read_notification_prefs(),
        "valid_severities": list(user_settings.VALID_ALERT_SEVERITIES),
    }


@router.put("/notifications")
def put_notification_prefs(body: NotificationPrefsIn) -> dict[str, Any]:
    """Update notification preferences (partial; persists to settings.yaml)."""
    try:
        prefs = user_settings.write_notification_prefs(
            enabled=body.enabled,
            min_severity=body.min_severity,
            muted_kinds=body.muted_kinds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**prefs, "valid_severities": list(user_settings.VALID_ALERT_SEVERITIES)}


@router.put("/data-provider", response_model=DataProviderOut)
def put_data_provider(body: DataProviderIn) -> DataProviderOut:
    """Set the provider and (optionally) its API-key secrets. Blank keys are kept."""
    try:
        settings = user_settings.write_provider_settings(
            body.provider,
            {
                "alpaca_api_key": body.alpaca_api_key,
                "alpaca_api_secret": body.alpaca_api_secret,
                "polygon_api_key": body.polygon_api_key,
            },
        )
    except user_settings.UnknownProviderError as exc:
        raise HTTPException(status_code=400, detail=f"unknown provider: {body.provider}") from exc
    return _to_out(settings)
