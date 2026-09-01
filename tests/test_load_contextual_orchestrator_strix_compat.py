"""Integration tests for the token loader's Strix-only compatibility handoff."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import subprocess


ROOT = Path(__file__).resolve().parents[1]
TOKEN_LOADER = ROOT / "scripts/ci/load_contextual_orchestrator_token.sh"
LAUNCHER = ROOT / "scripts/ci/strix_timeout_compat.py"


def sha256_file(path: Path) -> str:
    """Return the digest expected by the trusted executable handoff."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_token_loader_installs_strix_only_compatibility_launcher(tmp_path: Path) -> None:
    """A Strix consumer exports an immutable wrapper after masking its bearer."""
    token_file = tmp_path / "token"
    token_file.write_text("secret-token", encoding="utf-8")
    token_file.chmod(0o600)
    scripts_root = tmp_path / "bin"
    scripts_root.mkdir(mode=0o755)
    executable = scripts_root / "strix"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    github_env = tmp_path / "github-env"
    github_env.write_text("", encoding="utf-8")
    environment = os.environ | {
        "CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE": str(token_file),
        "GITHUB_ACTIONS": "true",
        "GITHUB_ENV": str(github_env),
        "STRIX_EXECUTABLE_PATH": str(executable),
        "STRIX_EXECUTABLE_ROOT": str(scripts_root),
        "STRIX_EXECUTABLE_SHA256": sha256_file(executable),
    }

    result = subprocess.run(
        [
            "bash",
            "-c",
            f"set -euo pipefail; source {TOKEN_LOADER!s}; "
            "test \"$CONTEXTUAL_ORCHESTRATOR_TOKEN\" = secret-token; "
            "! declare -F _contextual_orchestrator_install_strix_compat >/dev/null",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "::add-mask::secret-token" in result.stdout
    target = scripts_root / "strix-contextual-orchestrator"
    assert target.read_bytes() == LAUNCHER.read_bytes()
    assert target.stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH) == 0
    exported = github_env.read_text(encoding="utf-8")
    assert f"STRIX_EXECUTABLE_PATH={target}\n" in exported
    assert f"STRIX_EXECUTABLE_SHA256={sha256_file(target)}\n" in exported


def test_token_loader_leaves_non_strix_consumers_unchanged(tmp_path: Path) -> None:
    """Noema and OpenCode token loads do not install or export a Strix executable."""
    token_file = tmp_path / "token"
    token_file.write_text("secret-token", encoding="utf-8")
    token_file.chmod(0o600)
    github_env = tmp_path / "github-env"
    github_env.write_text("unchanged=1\n", encoding="utf-8")
    environment = os.environ | {
        "CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE": str(token_file),
        "GITHUB_ACTIONS": "true",
        "GITHUB_ENV": str(github_env),
    }
    environment.pop("STRIX_EXECUTABLE_PATH", None)

    result = subprocess.run(
        ["bash", "-c", f"set -euo pipefail; source {TOKEN_LOADER!s}"],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert github_env.read_text(encoding="utf-8") == "unchanged=1\n"
