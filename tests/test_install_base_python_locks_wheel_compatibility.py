"""Regression tests for binary-wheel compatibility in the coverage sandbox."""

from __future__ import annotations

from scripts.ci import install_base_python_locks as installer


def test_binary_only_unavailability_is_deferable() -> None:
    """A trusted pin without a wheel for the sandbox interpreter may be skipped."""

    output = "\n".join(
        (
            "ERROR: Could not find a version that satisfies the requirement "
            "atheris==3.0.0 (from versions: 3.1.0)",
            "ERROR: No matching distribution found for atheris==3.0.0",
        )
    )

    assert installer._is_deferable_preflight_failure(output)
