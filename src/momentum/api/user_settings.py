"""Writable user settings: the data-provider choice + API-key secrets.

The shipped ``config/*.example.yaml`` templates are read-only references. The
*user-editable* settings live in a per-user **writable** directory (``MRP_USER_DIR``;
the desktop app points this at ``%APPDATA%/Momentum Lab``). Two stores:

* ``settings.yaml`` — the non-secret data-provider choice (and any other tunables).
* ``.env`` — secrets (provider API keys). These are **never** returned in plain
  text by the API; callers only learn whether a key *is set* (a boolean).

Writes take effect immediately (the new secrets are pushed into ``os.environ`` so
the next provider build authenticates) and persist across restarts
(:func:`load_user_env` re-loads ``.env`` at startup).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from momentum.data.providers.base import MarketDataProvider

# Provider keys accepted by settings.yaml's ``data.provider`` (UI value -> impl).
VALID_PROVIDERS: tuple[str, ...] = ("yfinance", "alpaca", "polygon")
DEFAULT_PROVIDER = "yfinance"

# UI field name -> environment variable holding the secret. The env var names
# match what the provider adapters read (see data/providers/{alpaca,polygon}.py).
PROVIDER_KEYS: dict[str, str] = {
    "alpaca_api_key": "ALPACA_API_KEY",
    "alpaca_api_secret": "ALPACA_API_SECRET",
    "polygon_api_key": "POLYGON_API_KEY",
}


class UnknownProviderError(ValueError):
    """Raised when an unsupported provider name is written."""


@dataclass(frozen=True, slots=True)
class ProviderSettings:
    """Current data-provider selection and which secret keys are present."""

    provider: str
    keys_present: dict[str, bool]
    valid_providers: tuple[str, ...]


# --------------------------------------------------------------------------- #
# Paths (a single writable user directory, overridable for tests/desktop).
# --------------------------------------------------------------------------- #
def _user_dir() -> Path:
    override = os.environ.get("MRP_USER_DIR")
    if override:
        return Path(override).resolve()
    return Path.cwd().resolve()  # dev fallback: the repo root


def _settings_path() -> Path:
    return _user_dir() / "settings.yaml"


def _env_path() -> Path:
    return _user_dir() / ".env"


# --------------------------------------------------------------------------- #
# .env (KEY=value) — a minimal, dependency-free reader/writer that preserves
# any unrelated keys already in the file.
# --------------------------------------------------------------------------- #
def _read_env_file() -> dict[str, str]:
    path = _env_path()
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        out[key.strip()] = value.strip()
    return out


def _write_env_file(values: dict[str, str]) -> None:
    path = _env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in sorted(values.items())]
    path.write_text("\n".join(lines) + ("\n" if lines else ""))


# --------------------------------------------------------------------------- #
# settings.yaml — read/merge the data-provider choice, preserving other keys.
# --------------------------------------------------------------------------- #
def _read_settings_yaml() -> dict[str, object]:
    path = _settings_path()
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def read_provider() -> str:
    """The configured provider, or the default if unset/invalid."""
    section = _read_settings_yaml().get("data")
    if isinstance(section, dict):
        provider = section.get("provider")
        if isinstance(provider, str) and provider in VALID_PROVIDERS:
            return provider
    return DEFAULT_PROVIDER


def read_selected_universe() -> str:
    """The selected scanner-universe key (``"default"`` if unset)."""
    from momentum.universe.universes import DEFAULT_UNIVERSE_KEY

    section = _read_settings_yaml().get("universe")
    if isinstance(section, dict):
        selected = section.get("selected")
        if isinstance(selected, str) and selected:
            return selected
    return DEFAULT_UNIVERSE_KEY


def write_selected_universe(key: str) -> str:
    """Persist the selected scanner-universe key to ``settings.yaml``."""
    data = _read_settings_yaml()
    section = data.get("universe")
    if not isinstance(section, dict):
        section = {}
    section["selected"] = key
    data["universe"] = section
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return key


# Data mode: "demo" (sample data allowed) vs "production" (live data only).
VALID_DATA_MODES: tuple[str, ...] = ("demo", "production")
DEFAULT_DATA_MODE = "demo"


def read_data_mode() -> str:
    """The configured data mode (``"demo"`` if unset/invalid)."""
    section = _read_settings_yaml().get("data")
    if isinstance(section, dict):
        mode = section.get("mode")
        if isinstance(mode, str) and mode in VALID_DATA_MODES:
            return mode
    return DEFAULT_DATA_MODE


def write_data_mode(mode: str) -> str:
    """Persist the data mode to ``settings.yaml`` (under ``data.mode``)."""
    if mode not in VALID_DATA_MODES:
        raise ValueError(f"unknown data mode: {mode}")
    data = _read_settings_yaml()
    section = data.get("data")
    if not isinstance(section, dict):
        section = {}
    section["mode"] = mode
    data["data"] = section
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return mode


# Execution mode: which broker fills paper orders.
#   internal     — the deterministic in-process simulator (default; offline).
#   alpaca_paper — Alpaca's paper-trading API (real quotes/fills; needs keys).
VALID_EXECUTION_MODES: tuple[str, ...] = ("internal", "alpaca_paper")
DEFAULT_EXECUTION_MODE = "internal"


def read_execution_mode() -> str:
    """The configured execution mode (``"internal"`` if unset/invalid)."""
    section = _read_settings_yaml().get("execution")
    if isinstance(section, dict):
        mode = section.get("mode")
        if isinstance(mode, str) and mode in VALID_EXECUTION_MODES:
            return mode
    return DEFAULT_EXECUTION_MODE


def write_execution_mode(mode: str) -> str:
    """Persist the execution mode to ``settings.yaml`` (under ``execution.mode``)."""
    if mode not in VALID_EXECUTION_MODES:
        raise ValueError(f"unknown execution mode: {mode}")
    data = _read_settings_yaml()
    section = data.get("execution")
    if not isinstance(section, dict):
        section = {}
    section["mode"] = mode
    data["execution"] = section
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return mode


# Account balance: the paper book's starting equity (paper sessions, autopilot
# sizing context and new brokerage accounts all read it).
DEFAULT_ACCOUNT_BALANCE = 100_000.0


def read_account_balance() -> float:
    section = _read_settings_yaml().get("account")
    if isinstance(section, dict):
        balance = section.get("starting_balance")
        if isinstance(balance, (int, float)) and balance > 0:
            return float(balance)
    return DEFAULT_ACCOUNT_BALANCE


def write_account_balance(balance: float) -> float:
    if balance <= 0:
        raise ValueError("starting balance must be positive")
    data = _read_settings_yaml()
    section = data.get("account")
    if not isinstance(section, dict):
        section = {}
    section["starting_balance"] = float(balance)
    data["account"] = section
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return float(balance)


# Autopilot: the daemon takes committee-approved entries automatically.
# OFF by default — turning it on is an explicit, persisted user decision.
DEFAULT_AUTOPILOT: dict[str, object] = {
    "enabled": False,
    "max_open_positions": 8,
    "max_entries_per_cycle": 2,
    "min_conviction_score": 70.0,
    "include_premarket": False,
    # Automation Mode: the desktop shell holds a power-save blocker while
    # Auto Pilot runs (system sleep prevented; the display may still sleep).
    "prevent_sleep": True,
}


def read_autopilot() -> dict[str, object]:
    """Autopilot settings (defaults for anything unset/invalid)."""
    section = _read_settings_yaml().get("autopilot")
    out = dict(DEFAULT_AUTOPILOT)
    if isinstance(section, dict):
        if isinstance(section.get("enabled"), bool):
            out["enabled"] = section["enabled"]
        if isinstance(section.get("include_premarket"), bool):
            out["include_premarket"] = section["include_premarket"]
        if isinstance(section.get("prevent_sleep"), bool):
            out["prevent_sleep"] = section["prevent_sleep"]
        for key in ("max_open_positions", "max_entries_per_cycle"):
            value = section.get(key)
            if isinstance(value, int) and value > 0:
                out[key] = value
        score = section.get("min_conviction_score")
        if isinstance(score, (int, float)) and 0 <= score <= 100:
            out["min_conviction_score"] = float(score)
    return out


def write_autopilot(
    *,
    enabled: bool | None = None,
    max_open_positions: int | None = None,
    max_entries_per_cycle: int | None = None,
    min_conviction_score: float | None = None,
    include_premarket: bool | None = None,
    prevent_sleep: bool | None = None,
) -> dict[str, object]:
    """Persist autopilot settings (partial update)."""
    current = read_autopilot()
    if enabled is not None:
        current["enabled"] = enabled
    if include_premarket is not None:
        current["include_premarket"] = include_premarket
    if prevent_sleep is not None:
        current["prevent_sleep"] = prevent_sleep
    if max_open_positions is not None:
        if max_open_positions <= 0:
            raise ValueError("max_open_positions must be positive")
        current["max_open_positions"] = max_open_positions
    if max_entries_per_cycle is not None:
        if max_entries_per_cycle <= 0:
            raise ValueError("max_entries_per_cycle must be positive")
        current["max_entries_per_cycle"] = max_entries_per_cycle
    if min_conviction_score is not None:
        if not 0 <= min_conviction_score <= 100:
            raise ValueError("min_conviction_score must be 0..100")
        current["min_conviction_score"] = float(min_conviction_score)
    data = _read_settings_yaml()
    data["autopilot"] = current
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return current


# Notification preferences (OS alerts raised by the desktop shell).
VALID_ALERT_SEVERITIES: tuple[str, ...] = ("info", "warning", "critical")
DEFAULT_MIN_SEVERITY = "warning"


def read_notification_prefs() -> dict[str, object]:
    """OS-notification preferences (enabled flag, severity floor, muted kinds)."""
    section = _read_settings_yaml().get("notifications")
    enabled = True
    min_severity = DEFAULT_MIN_SEVERITY
    muted_kinds: list[str] = []
    if isinstance(section, dict):
        if isinstance(section.get("enabled"), bool):
            enabled = section["enabled"]
        sev = section.get("min_severity")
        if isinstance(sev, str) and sev in VALID_ALERT_SEVERITIES:
            min_severity = sev
        muted = section.get("muted_kinds")
        if isinstance(muted, list):
            muted_kinds = [str(k) for k in muted if isinstance(k, str) and k]
    return {"enabled": enabled, "min_severity": min_severity, "muted_kinds": muted_kinds}


def write_notification_prefs(
    *,
    enabled: bool | None = None,
    min_severity: str | None = None,
    muted_kinds: list[str] | None = None,
) -> dict[str, object]:
    """Persist notification preferences to ``settings.yaml`` (partial update)."""
    if min_severity is not None and min_severity not in VALID_ALERT_SEVERITIES:
        raise ValueError(f"unknown severity: {min_severity}")
    current = read_notification_prefs()
    if enabled is not None:
        current["enabled"] = enabled
    if min_severity is not None:
        current["min_severity"] = min_severity
    if muted_kinds is not None:
        current["muted_kinds"] = [k for k in muted_kinds if k]
    data = _read_settings_yaml()
    data["notifications"] = current
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return current


def build_broker(mode: str | None = None) -> object:
    """The broker for paper sessions, per the persisted execution mode.

    ``alpaca_paper`` falls back to the internal simulator (with a log line)
    when the Alpaca keys are missing — a session must never fail to run
    because of an unconfigured optional venue.
    """
    import logging

    from momentum.execution.execution_config import ExecutionConfig
    from momentum.execution.paper_broker import PaperBroker

    selected = (mode or read_execution_mode()).lower()
    if selected == "alpaca_paper":
        try:
            from momentum.execution.alpaca_broker import AlpacaPaperBroker

            load_user_env()
            return AlpacaPaperBroker()
        except Exception as exc:  # noqa: BLE001 — degrade to the simulator
            logging.getLogger(__name__).warning(
                "alpaca_paper unavailable (%s) — using the internal paper broker", exc
            )
    return PaperBroker(ExecutionConfig())


# --------------------------------------------------------------------------- #
# Public API.
# --------------------------------------------------------------------------- #
def read_provider_settings() -> ProviderSettings:
    """Current provider + per-key presence (file .env *or* live process env)."""
    env = _read_env_file()
    keys_present = {
        field: bool(env.get(var) or os.environ.get(var)) for field, var in PROVIDER_KEYS.items()
    }
    return ProviderSettings(read_provider(), keys_present, VALID_PROVIDERS)


def write_provider_settings(provider: str, secrets: dict[str, str | None]) -> ProviderSettings:
    """Persist the provider choice and any supplied secrets.

    A secret that is ``None`` or empty is left untouched (so the UI can submit
    blank fields to keep an existing key). New secrets are also pushed into
    ``os.environ`` so they take effect for the running process immediately.
    """
    if provider not in VALID_PROVIDERS:
        raise UnknownProviderError(provider)

    # 1. provider -> settings.yaml (merge under data.provider, keep other keys)
    data = _read_settings_yaml()
    section = data.get("data")
    if not isinstance(section, dict):
        section = {}
    section["provider"] = provider
    data["data"] = section
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))

    # 2. secrets -> .env (merge), and into the live process environment
    env = _read_env_file()
    for field, value in secrets.items():
        if field not in PROVIDER_KEYS or value is None or value == "":
            continue
        var = PROVIDER_KEYS[field]
        env[var] = value
        os.environ[var] = value
    _write_env_file(env)

    return read_provider_settings()


def clear_user_settings(*, preserve_api_keys: bool = True) -> dict[str, bool]:
    """Delete the writable user settings (factory reset). Returns what was removed.

    Removes ``settings.yaml`` (the provider choice resets to the default). API-key
    secrets in ``.env`` are preserved by default; when ``preserve_api_keys`` is
    ``False`` the ``.env`` file is removed and the provider vars are dropped from the
    live process environment too. Never raises on a missing file.
    """
    removed = {"settings_yaml": False, "env": False}
    settings_path = _settings_path()
    if settings_path.is_file():
        settings_path.unlink()
        removed["settings_yaml"] = True
    if not preserve_api_keys:
        env_path = _env_path()
        if env_path.is_file():
            env_path.unlink()
            removed["env"] = True
        for var in PROVIDER_KEYS.values():
            os.environ.pop(var, None)
    return removed


def load_user_env() -> None:
    """Load persisted ``.env`` secrets into the process environment at startup.

    Existing process-environment values win (``setdefault``), so an operator can
    still override a stored secret via the real environment.
    """
    for key, value in _read_env_file().items():
        os.environ.setdefault(key, value)


def build_provider(name: str | None = None) -> MarketDataProvider:
    """Construct the configured market-data provider (or an explicit ``name``).

    Alpaca/Polygon read their keys from the environment at construction; if the
    keys are missing the provider raises a clear auth error on first use.
    """
    provider = (name or read_provider()).lower()
    if provider == "alpaca":
        from momentum.data.providers.alpaca import AlpacaProvider

        return AlpacaProvider()
    if provider == "polygon":
        from momentum.data.providers.polygon import PolygonProvider

        return PolygonProvider()
    from momentum.data.providers.yfinance import YahooProvider

    return YahooProvider()
