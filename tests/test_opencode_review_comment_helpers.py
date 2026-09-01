"""Tests for the shared OpenCode review mermaid helper."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER = REPO_ROOT / "scripts/ci/opencode_review_comment_helpers.sh"


def test_mermaid_helper_labels_crates_as_rust_crate(tmp_path: Path) -> None:
    """Sourcing the publisher helper labels crates/ as a Rust crate surface."""
    bash = shutil.which("bash")
    if bash is None:
        return
    changed = tmp_path / "changed.txt"
    changed.write_text(
        "crates/originweave-destination/src/lib.rs\n"
        "crates/originweave-destination/src/resolution.rs\n"
        "crates/originweave-destination/tests/resolution_freshness.rs\n",
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "gh").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    (fake_bin / "gh").chmod(0o755)
    script = f"""
    set -euo pipefail
    . "{HELPER}"
    GH_REPOSITORY=ContextualWisdomLab/OriginWeave
    PR_NUMBER=47
    OPENCODE_CHANGED_FILES_FILE="{changed}"
    emit_change_flow_mermaid_graph UNKNOWN
    """
    result = subprocess.run(
        [bash, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"},
    )
    assert result.returncode == 0, result.stderr
    assert "Changed file (3 files)" not in result.stdout
    assert "originweave-destination" in result.stdout


def test_helper_sources_python_surfaces_module() -> None:
    """The shared helper delegates mermaid rendering to the tested Python module."""
    text = HELPER.read_text(encoding="utf-8")
    assert "opencode_review_surfaces.py" in text
    assert 'add("other", "Changed file"' not in text
