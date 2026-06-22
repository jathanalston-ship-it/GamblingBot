"""Tests for robust config-path resolution (source AND packaged builds)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from momentum.core import config_paths as cp


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test controls the env explicitly (no ambient overrides)."""
    monkeypatch.delenv("MRP_USER_DIR", raising=False)
    monkeypatch.delenv("MRP_CONFIG_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)


def test_user_config_dir_uses_mrp_user_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))
    assert cp.user_config_dir() == tmp_path.resolve() / "config"


def test_bundled_config_dir_source_points_at_repo_config() -> None:
    # Source checkout: the real repo config/ exists and holds the example YAMLs.
    d = cp.bundled_config_dir()
    assert d.name == "config"
    assert (d / "watchlist.example.yaml").is_file()


def test_bundled_config_dir_frozen_uses_meipass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # PACKAGED-BUILD path: must read from the bundle (sys._MEIPASS/config), NOT the
    # source tree (parents[3]) — that was the FileNotFoundError root cause.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert cp.bundled_config_dir() == tmp_path / "config"


def test_load_config_prefers_user_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    user = tmp_path / "user"
    (user / "config").mkdir(parents=True)
    (user / "config" / "foo.yaml").write_text(yaml.safe_dump({"who": "user"}))
    monkeypatch.setenv("MRP_USER_DIR", str(user))
    monkeypatch.setenv("MRP_CONFIG_DIR", str(tmp_path / "bundle"))  # would lose to user

    assert cp.load_config("foo.example.yaml", embedded={"who": "embedded"}) == {"who": "user"}


def test_load_config_bootstraps_from_bundled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "foo.example.yaml").write_text(yaml.safe_dump({"who": "bundled"}))
    user = tmp_path / "user"
    monkeypatch.setenv("MRP_USER_DIR", str(user))
    monkeypatch.setenv("MRP_CONFIG_DIR", str(bundle))

    data = cp.load_config("foo.example.yaml")
    assert data == {"who": "bundled"}
    # A writable user copy was bootstrapped automatically.
    assert (user / "config" / "foo.yaml").is_file()
    assert yaml.safe_load((user / "config" / "foo.yaml").read_text()) == {"who": "bundled"}


def test_load_config_embedded_when_no_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # FRESH INSTALL with no config files anywhere: the in-code default is used and
    # bootstrapped — a packaged build never *requires* a repository/bundle file.
    user = tmp_path / "user"
    monkeypatch.setenv("MRP_USER_DIR", str(user))
    monkeypatch.setenv("MRP_CONFIG_DIR", str(tmp_path / "nonexistent"))

    data = cp.load_config("foo.example.yaml", embedded={"who": "embedded"})
    assert data == {"who": "embedded"}
    assert (user / "config" / "foo.yaml").is_file()


def test_load_config_raises_without_file_or_embedded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path / "user"))
    monkeypatch.setenv("MRP_CONFIG_DIR", str(tmp_path / "none"))
    with pytest.raises(FileNotFoundError):
        cp.load_config("missing.example.yaml")


def test_invalid_user_config_falls_back_to_embedded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    user = tmp_path / "user"
    (user / "config").mkdir(parents=True)
    (user / "config" / "foo.yaml").write_text("{ this is : not : valid : yaml")
    monkeypatch.setenv("MRP_USER_DIR", str(user))
    monkeypatch.setenv("MRP_CONFIG_DIR", str(tmp_path / "none"))

    assert cp.load_config("foo.example.yaml", embedded={"who": "embedded"}) == {"who": "embedded"}


def test_bootstrap_failure_is_non_fatal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # An unwritable user dir must not break loading — defaults are returned in
    # memory. Point the user config dir under a FILE so mkdir raises OSError.
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory")
    monkeypatch.setattr(cp, "user_config_dir", lambda: blocker / "config")
    monkeypatch.setenv("MRP_CONFIG_DIR", str(tmp_path / "none"))

    assert cp.load_config("foo.example.yaml", embedded={"ok": True}) == {"ok": True}
