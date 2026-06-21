"""Tests for production-grade secret management (momentum.core.secrets)."""

from __future__ import annotations

import logging

import pytest

from momentum.core import secrets
from momentum.core.secrets import MissingSecretsError, RedactingFormatter

# A long, obviously-fake secret value used throughout (>= the redaction floor).
FAKE = "AKFAKEKEY1234567890SECRETVALUE"


# --------------------------------------------------------------------------- #
# Registry.
# --------------------------------------------------------------------------- #
def test_registry_env_vars_are_unique() -> None:
    names = [s.env_var for s in secrets.SECRET_REGISTRY]
    assert len(names) == len(set(names))
    assert set(secrets.SECRETS_BY_ENV) == set(names)


def test_required_specs_by_provider_and_environment() -> None:
    alpaca = {s.env_var for s in secrets.required_specs(provider="alpaca", environment="research")}
    assert alpaca == {"ALPACA_API_KEY", "ALPACA_API_SECRET"}

    polygon = {
        s.env_var for s in secrets.required_specs(provider="polygon", environment="research")
    }
    assert polygon == {"POLYGON_API_KEY"}

    # The default provider needs no secrets.
    assert secrets.required_specs(provider="yfinance", environment="research") == ()

    # Live execution additionally requires the broker credentials.
    live = {s.env_var for s in secrets.required_specs(provider="yfinance", environment="live")}
    assert live == {"BROKER_API_KEY", "BROKER_API_SECRET"}


def test_optional_secrets_are_never_required() -> None:
    for env in ("research", "paper", "live"):
        for prov in secrets.SECRETS_BY_ENV:
            req = secrets.required_specs(provider="alpaca", environment=env)
            assert all(not s.optional for s in req)
    assert secrets.SECRETS_BY_ENV["MRP_UPDATE_TOKEN"].optional is True


# --------------------------------------------------------------------------- #
# Reads.
# --------------------------------------------------------------------------- #
def test_get_strips_and_treats_blank_as_unset() -> None:
    assert secrets.get("X", env={"X": "  abc  "}) == "abc"
    assert secrets.get("X", env={"X": "   "}) is None
    assert secrets.get("X", env={}) is None
    assert secrets.is_set("X", env={"X": "abc"}) is True
    assert secrets.is_set("X", env={"X": ""}) is False


# --------------------------------------------------------------------------- #
# Validation.
# --------------------------------------------------------------------------- #
def test_validate_missing_lists_env_var_names_only() -> None:
    report = secrets.validate(provider="alpaca", environment="research", env={})
    assert report.ok is False
    assert set(report.missing) == {"ALPACA_API_KEY", "ALPACA_API_SECRET"}
    # The message names the env vars but never a value.
    assert "ALPACA_API_KEY" in report.message()
    assert "Never commit" in report.message()


def test_validate_ok_when_present() -> None:
    env = {"ALPACA_API_KEY": FAKE, "ALPACA_API_SECRET": FAKE}
    report = secrets.validate(provider="alpaca", environment="research", env=env)
    assert report.ok is True
    assert report.missing == ()
    # Even a passing report must not echo the value.
    assert FAKE not in report.message()


def test_validate_default_provider_is_always_ok() -> None:
    report = secrets.validate(provider="yfinance", environment="research", env={})
    assert report.ok is True


def test_require_raises_value_free_error() -> None:
    with pytest.raises(MissingSecretsError) as exc:
        secrets.require(provider="polygon", environment="research", env={})
    assert exc.value.missing == ("POLYGON_API_KEY",)
    assert "POLYGON_API_KEY" in str(exc.value)
    assert FAKE not in str(exc.value)


def test_require_returns_report_when_ok() -> None:
    report = secrets.require(provider="yfinance", environment="paper", env={})
    assert report.ok is True


# --------------------------------------------------------------------------- #
# Masking / redaction.
# --------------------------------------------------------------------------- #
def test_mask_hides_everything() -> None:
    assert secrets.mask(FAKE) == "••••••••"
    assert FAKE not in secrets.mask(FAKE)
    assert secrets.mask(None) == "—"
    assert secrets.mask("") == "—"


def test_redact_text_replaces_known_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", FAKE)
    text = f"connecting with key={FAKE} to alpaca"
    out = secrets.redact_text(text)
    assert FAKE not in out
    assert "<redacted>" in out


def test_redact_text_ignores_short_values(monkeypatch: pytest.MonkeyPatch) -> None:
    # A pathologically short value must not be redacted (would mangle every log).
    monkeypatch.setenv("ALPACA_API_KEY", "ab")
    assert secrets.redact_text("value ab here") == "value ab here"


def test_redact_text_handles_no_secrets() -> None:
    assert secrets.redact_text("nothing secret here", env={}) == "nothing secret here"
    assert secrets.redact_text("", env={}) == ""


def test_redacting_formatter_scrubs_a_logged_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLYGON_API_KEY", FAKE)
    fmt = RedactingFormatter(logging.Formatter("%(message)s"))
    record = logging.makeLogRecord({"msg": "using POLYGON_API_KEY=%s", "args": (FAKE,)})
    out = fmt.format(record)
    assert FAKE not in out
    assert "<redacted>" in out


def test_redacting_formatter_scrubs_exception_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_SECRET", FAKE)
    fmt = RedactingFormatter(logging.Formatter("%(message)s"))
    try:
        raise ValueError(f"auth failed for secret {FAKE}")
    except ValueError:
        import sys

        record = logging.makeLogRecord({"msg": "boom", "exc_info": sys.exc_info()})
    out = fmt.format(record)
    assert FAKE not in out


# --------------------------------------------------------------------------- #
# Single-source-of-truth guards.
# --------------------------------------------------------------------------- #
def test_user_settings_provider_keys_are_registered() -> None:
    from momentum.api.user_settings import PROVIDER_KEYS

    for env_var in PROVIDER_KEYS.values():
        assert env_var in secrets.SECRETS_BY_ENV, f"{env_var} missing from the secret registry"


def test_env_example_lists_every_required_secret() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    text = (root / ".env.example").read_text()
    for spec in secrets.SECRET_REGISTRY:
        if not spec.optional:
            assert f"{spec.env_var}=" in text, f"{spec.env_var} missing from .env.example"


def test_env_example_contains_no_secret_values() -> None:
    """Every secret line in .env.example must have an EMPTY value."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    for raw in (root / ".env.example").read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() in secrets.SECRETS_BY_ENV:
            assert value.strip() == "", f"{key} has a non-empty value in .env.example"
