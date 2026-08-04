"""Regression tests for unavailable pins in trusted base Python locks."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest

from scripts.ci import install_base_python_locks as installer


def _write_candidate(root: Path) -> None:
    """Write one trusted materialized lock candidate and its manifest."""

    (root / "manifest.json").write_text(
        json.dumps(
            [
                {
                    "file": "requirements-000.txt",
                    "source": "requirements-hashes.txt",
                }
            ]
        ),
        encoding="utf-8",
    )
    (root / "requirements-000.txt").write_text(
        "pypdf==6.13.3 --hash=sha256:" + ("a" * 64) + "\n",
        encoding="utf-8",
    )


def _run_preflight_failure(root: Path, output: str) -> tuple[int, str, str]:
    """Run the installer with one deterministic pip preflight failure."""

    _write_candidate(root)

    def fake_runner(command: list[str], **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout=output)

    stdout = io.StringIO()
    stderr = io.StringIO()
    result = installer.install_materialized_locks(
        root,
        runner=fake_runner,
        stdout=stdout,
        stderr=stderr,
    )
    return result, stdout.getvalue(), stderr.getvalue()


def test_reachable_index_missing_pin_is_visible_and_nonfatal(tmp_path: Path) -> None:
    """A reachable index proving newer versions exist may defer a stale pin."""

    output = (
        "ERROR: Could not find a version that satisfies the requirement "
        "pypdf==6.13.3 (from versions: 6.14.1, 6.14.2)\n"
        "ERROR: No matching distribution found for pypdf==6.13.3"
    )

    result, stdout, stderr = _run_preflight_failure(tmp_path, output)

    assert result == 0
    assert "candidates=1 installed=0 skipped=1" in stdout
    assert "Could not find a version that satisfies the requirement" in stderr


@pytest.mark.parametrize(
    "fatal_fragment",
    [
        "ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE",
        "WARNING: Retrying after connection broken by ConnectionError",
        "ERROR: Could not fetch URL https://pypi.org/simple/pypdf/",
    ],
)
def test_reachable_index_message_cannot_mask_fatal_failure(
    tmp_path: Path,
    fatal_fragment: str,
) -> None:
    """Integrity or transport evidence must dominate a stale-pin diagnostic."""

    output = (
        "ERROR: Could not find a version that satisfies the requirement "
        "pypdf==6.13.3 (from versions: 6.14.1, 6.14.2)\n"
        "ERROR: No matching distribution found for pypdf==6.13.3\n"
        f"{fatal_fragment}"
    )

    result, stdout, stderr = _run_preflight_failure(tmp_path, output)

    assert result == 1
    assert "preflight failed" in stderr
    assert fatal_fragment in stderr
    assert "installed=" not in stdout


def test_empty_index_missing_pin_remains_fatal(tmp_path: Path) -> None:
    """An explicitly empty package index must never be treated as optional."""

    output = (
        "ERROR: Could not find a version that satisfies the requirement "
        "pypdf==6.13.3 (from versions: none)\n"
        "ERROR: No matching distribution found for pypdf==6.13.3"
    )

    result, stdout, stderr = _run_preflight_failure(tmp_path, output)

    assert result == 1
    assert "preflight failed" in stderr
    assert "installed=" not in stdout


def test_blank_version_list_missing_pin_remains_fatal(tmp_path: Path) -> None:
    """A blank version list is not affirmative proof that the index is reachable."""

    output = (
        "ERROR: Could not find a version that satisfies the requirement "
        "pypdf==6.13.3 (from versions: )\n"
        "ERROR: No matching distribution found for pypdf==6.13.3"
    )

    result, stdout, stderr = _run_preflight_failure(tmp_path, output)

    assert result == 1
    assert "preflight failed" in stderr
    assert "installed=" not in stdout
