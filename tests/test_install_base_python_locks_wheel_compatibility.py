"""Regression tests for binary-wheel compatibility in the coverage sandbox."""

from __future__ import annotations

import io
import json
import subprocess

import pytest

from scripts.ci import install_base_python_locks as installer


ATHERIS_BINARY_MISMATCH = "\n".join(
    (
        "ERROR: Could not find a version that satisfies the requirement "
        "atheris==3.0.0 (from versions: 3.1.0)",
        "ERROR: No matching distribution found for atheris==3.0.0",
    )
)


def test_binary_only_unavailability_is_deferable() -> None:
    """A trusted pin without a wheel for the sandbox interpreter may be skipped."""

    assert installer._is_deferable_preflight_failure(ATHERIS_BINARY_MISMATCH)


@pytest.mark.parametrize(
    "output",
    (
        (
            "ERROR: Could not find a version that satisfies the requirement "
            "atheris==3.0.0 (from versions: 3.1.0)"
        ),
        "ERROR: No matching distribution found for atheris==3.0.0",
        "\n".join(
            (
                "ERROR: Could not find a version that satisfies the requirement "
                "atheris==3.0.0 (from versions: 3.1.0)",
                "ERROR: No matching distribution found for atheris==3.1.0",
            )
        ),
        ATHERIS_BINARY_MISMATCH
        + "\nWARNING: Retrying after connection broken by ConnectionError",
        ATHERIS_BINARY_MISMATCH
        + "\nERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE",
        ATHERIS_BINARY_MISMATCH
        + "\nERROR: Could not fetch URL https://pypi.org/simple/atheris/",
    ),
)
def test_ambiguous_or_integrity_sensitive_binary_failures_remain_fatal(
    output: str,
) -> None:
    """One-sided, mismatched, network, and integrity diagnostics fail closed."""

    assert not installer._is_deferable_preflight_failure(output)


def test_binary_mismatch_candidate_is_visible_and_deferred(tmp_path) -> None:
    """The installer warns and defers a wheel mismatch to networkless coverage."""

    (tmp_path / "manifest.json").write_text(
        json.dumps(
            [
                {
                    "file": "requirements-000.txt",
                    "source": "fuzz/requirements-atheris.txt",
                }
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "requirements-000.txt").write_text(
        "atheris==3.0.0 --hash=sha256:" + ("a" * 64) + "\n",
        encoding="utf-8",
    )

    def fake_runner(command: list[str], **kwargs):
        """Return the observed binary-only resolver failure for the candidate."""

        return subprocess.CompletedProcess(
            command,
            1,
            stdout=ATHERIS_BINARY_MISMATCH,
        )

    stdout = io.StringIO()
    stderr = io.StringIO()
    result = installer.install_materialized_locks(
        tmp_path,
        runner=fake_runner,
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "fuzz/requirements-atheris.txt" in stderr.getvalue()
    assert ATHERIS_BINARY_MISMATCH in stderr.getvalue()
    assert "candidates=1 installed=0 skipped=1" in stdout.getvalue()
