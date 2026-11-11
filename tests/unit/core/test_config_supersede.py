"""A user config bootstrapped from OLD shipped defaults must not pin the app to them."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from momentum.core.config_paths import load_config


@pytest.fixture
def dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    user, bundled = tmp_path / "user", tmp_path / "bundled"
    (user / "config").mkdir(parents=True)
    bundled.mkdir()
    monkeypatch.setenv("MRP_USER_DIR", str(user))
    monkeypatch.setenv("MRP_CONFIG_DIR", str(bundled))
    return user / "config", bundled


def test_same_version_user_file_wins(dirs: tuple[Path, Path]) -> None:
    user, bundled = dirs
    (bundled / "x.example.yaml").write_text(yaml.safe_dump({"model_version": "v2", "knob": 1}))
    (user / "x.yaml").write_text(yaml.safe_dump({"model_version": "v2", "knob": 99}))
    assert load_config("x.example.yaml")["knob"] == 99  # a deliberate user edit is kept


def test_old_version_user_file_is_retired(dirs: tuple[Path, Path]) -> None:
    user, bundled = dirs
    (bundled / "x.example.yaml").write_text(yaml.safe_dump({"model_version": "v2", "knob": 1}))
    (user / "x.yaml").write_text(yaml.safe_dump({"model_version": "v1", "knob": 99}))
    assert load_config("x.example.yaml") == {"model_version": "v2", "knob": 1}
    # The old file is kept as a backup and the new defaults are re-bootstrapped.
    assert yaml.safe_load((user / "x.yaml.bak").read_text())["knob"] == 99
    assert yaml.safe_load((user / "x.yaml").read_text())["knob"] == 1
    assert load_config("x.example.yaml")["knob"] == 1  # stable on the next load


def test_unversioned_files_keep_the_old_behaviour(dirs: tuple[Path, Path]) -> None:
    user, bundled = dirs
    (bundled / "x.example.yaml").write_text(yaml.safe_dump({"knob": 1}))
    (user / "x.yaml").write_text(yaml.safe_dump({"knob": 99}))
    assert load_config("x.example.yaml")["knob"] == 99
    assert not (user / "x.yaml.bak").exists()


def test_user_file_without_any_shipped_default_still_loads(dirs: tuple[Path, Path]) -> None:
    user, _bundled = dirs
    (user / "x.yaml").write_text(yaml.safe_dump({"model_version": "v1", "knob": 7}))
    assert load_config("x.example.yaml")["knob"] == 7
