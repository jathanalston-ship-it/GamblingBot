"""Domain exception hierarchy.

A single rooted tree (``MomentumError``) so callers can catch broadly
(``except MomentumError``) or narrowly (``except ProviderRateLimitError``).
Only the data-layer branch is implemented here; sibling branches
(``RiskVetoError``, ``ExecutionError``, ...) are declared as stubs so the
hierarchy is stable for the rest of the platform to import.
"""

from __future__ import annotations


class MomentumError(Exception):
    """Root of every platform-specific exception."""


# --------------------------------------------------------------------------- #
# Data layer
# --------------------------------------------------------------------------- #
class DataError(MomentumError):
    """Base for every market-data-layer failure."""


class ProviderError(DataError):
    """A market-data vendor adapter failed to return usable data."""

    def __init__(self, message: str, *, provider: str | None = None) -> None:
        self.provider = provider
        super().__init__(f"[{provider}] {message}" if provider else message)


class ProviderAuthError(ProviderError):
    """Missing/invalid credentials (HTTP 401/403)."""


class ProviderRateLimitError(ProviderError):
    """The vendor throttled us (HTTP 429)."""


class ProviderNotFoundError(ProviderError):
    """The requested symbol / resource does not exist (HTTP 404)."""


class SchemaError(DataError):
    """A DataFrame did not satisfy the canonical OHLCV contract."""


class DataValidationError(DataError):
    """A data-quality gate rejected a bar series."""


class CacheError(DataError):
    """The local cache could not be read or written."""


# --------------------------------------------------------------------------- #
# Sibling branches (declared for a stable hierarchy; filled in by later phases)
# --------------------------------------------------------------------------- #
class ConfigError(MomentumError):
    """Invalid or inconsistent configuration."""


class RiskVetoError(MomentumError):
    """The risk engine vetoed an action."""


class ExecutionError(MomentumError):
    """Order routing / fill handling failed."""


class InvalidOrderStateError(ExecutionError):
    """An order was asked to make an illegal lifecycle transition."""


class UpdateError(MomentumError):
    """The local self-update failed (and was rolled back)."""


class GitError(UpdateError):
    """A git operation invoked by the updater failed."""
