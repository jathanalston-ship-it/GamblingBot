"""Production-grade secret management — the single source of truth for credentials.

Every credential the platform consumes is declared here once. Secrets live **only**
in the process environment (loaded from a git-ignored ``.env`` under ``MRP_USER_DIR``
by :func:`momentum.api.user_settings.load_user_env`); they are **never** hard-coded
in source, config, example YAML, ``package.json`` or ``pyproject.toml``.

This module provides:

* the **secret registry** (env var, description, which provider / environment needs it);
* **validation** that the secrets required by the *active* configuration are present,
  with a clear, **value-free** error when they are missing (:func:`validate`,
  :func:`require`, :class:`MissingSecretsError`);
* **masking / redaction** so a secret value can never reach a log line
  (:func:`mask`, :func:`redact_text`, :class:`RedactingFormatter`).

Pure and dependency-free (stdlib only) so it can be imported anywhere and unit-tested
without a real environment.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from momentum.core.exceptions import ConfigError

Env = Mapping[str, str]

# Values shorter than this are never treated as redactable secret material — real
# API keys/tokens are long, and redacting a 1–2 char value would mangle every log.
_MIN_REDACT_LEN = 6


@dataclass(frozen=True, slots=True)
class SecretSpec:
    """A declared secret: the env var that holds it and what makes it *required*."""

    env_var: str
    description: str
    # Data providers that require this secret (e.g. ("alpaca",)).
    providers: tuple[str, ...] = field(default_factory=tuple)
    # Execution environments that require it (e.g. ("live",)). () = never env-gated.
    environments: tuple[str, ...] = field(default_factory=tuple)
    # Optional secrets are redacted from logs but never *required*.
    optional: bool = False

    def required_for(self, *, provider: str, environment: str) -> bool:
        return provider in self.providers or environment in self.environments


# --------------------------------------------------------------------------- #
# The registry — the ONLY place a credential's env var is declared.
# --------------------------------------------------------------------------- #
SECRET_REGISTRY: tuple[SecretSpec, ...] = (
    SecretSpec("ALPACA_API_KEY", "Alpaca market-data / broker API key", providers=("alpaca",)),
    SecretSpec("ALPACA_API_SECRET", "Alpaca API secret", providers=("alpaca",)),
    SecretSpec("POLYGON_API_KEY", "Polygon.io market-data API key", providers=("polygon",)),
    SecretSpec("BROKER_API_KEY", "Broker API key (paper/live execution)", environments=("live",)),
    SecretSpec("BROKER_API_SECRET", "Broker API secret", environments=("live",)),
    # Optional: redacted from logs but never required (private-repo auto-update auth).
    SecretSpec("MRP_UPDATE_TOKEN", "GitHub token for private-repo auto-update", optional=True),
    SecretSpec("GH_TOKEN", "GitHub token (auto-update / CI)", optional=True),
    SecretSpec("GITHUB_TOKEN", "GitHub token (auto-update / CI)", optional=True),
)

# Fast lookup by env var.
SECRETS_BY_ENV: dict[str, SecretSpec] = {s.env_var: s for s in SECRET_REGISTRY}


@dataclass(frozen=True, slots=True)
class SecretStatus:
    """Presence of one secret — **never** carries the value."""

    env_var: str
    description: str
    present: bool


@dataclass(frozen=True, slots=True)
class SecretReport:
    """The result of validating the active configuration's required secrets."""

    provider: str
    environment: str
    required: tuple[SecretStatus, ...]
    missing: tuple[str, ...]  # env var names only — no values

    @property
    def ok(self) -> bool:
        return not self.missing

    def message(self) -> str:
        """A clear, value-free summary (safe to log/show)."""
        if self.ok:
            present = ", ".join(s.env_var for s in self.required) or "none required"
            return (
                f"All required secrets present (provider={self.provider}, "
                f"environment={self.environment}): {present}."
            )
        return (
            f"Missing required secret(s) for provider '{self.provider}' / environment "
            f"'{self.environment}': {', '.join(self.missing)}. Set them in your environment "
            f"or in the .env file under MRP_USER_DIR (see .env.example). Never commit real secrets."
        )


class MissingSecretsError(ConfigError):
    """Required secrets are absent. The message is **value-free** by construction."""

    def __init__(self, report: SecretReport) -> None:
        self.report = report
        self.missing = report.missing
        super().__init__(report.message())


# --------------------------------------------------------------------------- #
# Reads.
# --------------------------------------------------------------------------- #
def _env(env: Env | None) -> Env:
    return os.environ if env is None else env


def get(env_var: str, env: Env | None = None) -> str | None:
    """The secret value (stripped), or ``None`` if unset/blank. Use sparingly."""
    raw = _env(env).get(env_var)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def is_set(env_var: str, env: Env | None = None) -> bool:
    """Whether a secret is present (non-blank) — the safe presence check."""
    return get(env_var, env) is not None


def required_specs(*, provider: str, environment: str) -> tuple[SecretSpec, ...]:
    """The secrets required by this provider/environment (excludes optionals)."""
    return tuple(
        s
        for s in SECRET_REGISTRY
        if not s.optional and s.required_for(provider=provider, environment=environment)
    )


# --------------------------------------------------------------------------- #
# Validation.
# --------------------------------------------------------------------------- #
def validate(*, provider: str, environment: str, env: Env | None = None) -> SecretReport:
    """Report which required secrets are present/missing (never raises)."""
    statuses: list[SecretStatus] = []
    missing: list[str] = []
    for spec in required_specs(provider=provider, environment=environment):
        present = is_set(spec.env_var, env)
        statuses.append(SecretStatus(spec.env_var, spec.description, present))
        if not present:
            missing.append(spec.env_var)
    return SecretReport(provider, environment, tuple(statuses), tuple(missing))


def require(*, provider: str, environment: str, env: Env | None = None) -> SecretReport:
    """Validate and **raise** :class:`MissingSecretsError` if anything is missing."""
    report = validate(provider=provider, environment=environment, env=env)
    if not report.ok:
        raise MissingSecretsError(report)
    return report


# --------------------------------------------------------------------------- #
# Masking / redaction — a secret value must never reach a log or the renderer.
# --------------------------------------------------------------------------- #
def mask(value: str | None) -> str:
    """A fixed, length-hiding mask for display (``"••••••••"`` / ``"—"``)."""
    return "••••••••" if value else "—"


def secret_values(env: Env | None = None) -> list[str]:
    """Current non-blank values of every *registered* secret (for redaction)."""
    out: list[str] = []
    for spec in SECRET_REGISTRY:
        v = get(spec.env_var, env)
        if v is not None and len(v) >= _MIN_REDACT_LEN:
            out.append(v)
    return out


def redact_text(text: str, env: Env | None = None) -> str:
    """Replace every known secret value occurring in *text* with ``<redacted>``."""
    if not text:
        return text
    redacted = text
    # Longest first so a key that contains a shorter one is fully masked.
    for value in sorted(secret_values(env), key=len, reverse=True):
        if value in redacted:
            redacted = redacted.replace(value, "<redacted>")
    return redacted


class RedactingFormatter(logging.Formatter):
    """Wrap a formatter so its output is scrubbed of any known secret value.

    This is the last line of defence: even if code accidentally logs a secret
    (in the message, args, an exception or a structured extra), the formatted
    string is redacted before it is written to any handler.
    """

    def __init__(self, inner: logging.Formatter) -> None:
        super().__init__()
        self._inner = inner

    def format(self, record: logging.LogRecord) -> str:
        return redact_text(self._inner.format(record))
