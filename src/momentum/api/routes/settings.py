"""Settings endpoints.

Reading the configuration templates is side-effect free. The data-provider
selection is editable via a small, explicitly-guarded write endpoint
(``PUT /settings/data-provider``) that persists the choice to ``settings.yaml``
and any API-key secrets to ``.env`` (secrets are never read back in plain text).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from momentum.api import services, user_settings
from momentum.api.schemas import ConfigFileOut, DataProviderIn, DataProviderOut

router = APIRouter(prefix="/settings", tags=["settings"])


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
