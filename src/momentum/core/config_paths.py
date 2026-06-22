"""Robust config-path resolution for source **and** packaged (PyInstaller) builds.

The bug this fixes: every engine's ``default_config()`` resolved its tunables as
``Path(__file__).resolve().parents[3] / "config" / "<name>.example.yaml"`` — an
assumption that the code runs from a source checkout (``src/momentum/<pkg>/`` → up
3 → repo root → ``config/``). In a **frozen** build that path points *outside* the
bundle (PyInstaller lays the package out as ``<_MEIPASS>/momentum/...`` and the
shipped data at ``<_MEIPASS>/config``), so the read raised ``FileNotFoundError``.

This module resolves three locations so config loading never assumes a source
checkout and **packaged builds never require repository files**:

1. a writable **user override** — ``<MRP_USER_DIR>/config/<name>.yaml`` (e.g.
   ``%APPDATA%/Momentum Lab/config``);
2. the **shipped example** — the bundle (``<_MEIPASS>/config``) when frozen, the
   repo (``<root>/config``) from source;
3. in-code **embedded defaults** — so a build with no config files at all still works.

On first use the resolved defaults are **bootstrapped** to the user dir (best
effort), so a default configuration is created automatically and is editable from
then on.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

import yaml

_log = logging.getLogger("momentum.core.config")


def user_config_dir() -> Path:
    """The writable per-user config directory (``<MRP_USER_DIR>/config``)."""
    base = os.environ.get("MRP_USER_DIR")
    root = Path(base).resolve() if base else Path.cwd().resolve()
    return root / "config"


def bundled_config_dir() -> Path:
    """Where the shipped example YAMLs live: the bundle (frozen) or the repo (source).

    Honours ``MRP_CONFIG_DIR`` as an explicit override (used by the Settings view
    and tests).
    """
    override = os.environ.get("MRP_CONFIG_DIR")
    if override:
        return Path(override).resolve()
    if getattr(sys, "frozen", False):  # PyInstaller: data is unpacked beside the app
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        return base / "config"
    # Source checkout: src/momentum/core/config_paths.py -> repo root is 3 up.
    return Path(__file__).resolve().parents[3] / "config"


def _user_name(example_name: str) -> str:
    """``watchlist.example.yaml`` -> ``watchlist.yaml`` (the user-override name)."""
    return example_name.replace(".example", "")


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    return data if isinstance(data, dict) else {}


def _bootstrap(path: Path, data: dict[str, Any]) -> None:
    """Write *data* to *path* so a default config exists + is editable. Best-effort."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, sort_keys=False))
        _log.info("bootstrapped default config: %s", path)
    except OSError:
        # Read-only filesystem etc. — the in-memory defaults are still returned.
        _log.warning("could not write default config %s; using in-memory defaults", path)


def load_config(example_name: str, *, embedded: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load tunables for *example_name* (e.g. ``"watchlist.example.yaml"``).

    Resolution order: writable user override → shipped example → in-code embedded
    defaults. The first time defaults are used they are bootstrapped to the user
    config dir. Never assumes a source checkout; never requires a repository file
    (when *embedded* is supplied).
    """
    user_path = user_config_dir() / _user_name(example_name)
    if user_path.is_file():
        try:
            return _read_yaml(user_path)
        except (OSError, yaml.YAMLError):
            _log.warning(
                "invalid user config %s; falling back to shipped/embedded defaults", user_path
            )

    data: dict[str, Any] | None = None
    bundled = bundled_config_dir() / example_name
    if bundled.is_file():
        try:
            data = _read_yaml(bundled)
        except (OSError, yaml.YAMLError):
            data = None
    if data is None and embedded is not None:
        data = dict(embedded)
    if data is None:
        raise FileNotFoundError(
            f"no configuration for {example_name!r}: looked in {user_path} and {bundled}, "
            "and no embedded default was provided"
        )

    _bootstrap(user_path, data)
    return data
