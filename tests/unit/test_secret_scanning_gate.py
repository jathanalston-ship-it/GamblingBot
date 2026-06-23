"""Guard the secret-scanning gate itself — so it can't be silently removed.

The real protection is the gitleaks CI job (.github/workflows/secret-scan.yml) +
the release quality gate + the pre-commit hook. These tests assert that wiring
exists and is configured to *fail* on a finding, so a future change can't quietly
drop the secret scanner.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_gitleaks_config_uses_default_rules() -> None:
    cfg = (ROOT / ".gitleaks.toml").read_text()
    assert "useDefault = true" in cfg


def test_secret_scan_workflow_exists_and_fails_on_findings() -> None:
    wf = (ROOT / ".github" / "workflows" / "secret-scan.yml").read_text()
    assert "gitleaks" in wf
    assert "fetch-depth: 0" in wf  # scans the full history, not just the tip
    assert "--exit-code 1" in wf  # a finding fails the build
    assert "--redact" in wf  # never print a detected secret


def test_release_quality_gate_includes_secret_scan() -> None:
    rel = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    # The publish path must be gated too: a release can't ship with a secret.
    assert "gitleaks" in rel
    assert "--exit-code 1" in rel


def test_precommit_hook_runs_gitleaks() -> None:
    pc = (ROOT / ".pre-commit-config.yaml").read_text()
    assert "gitleaks" in pc
