"""Regression tests for unavailable pins in trusted base Python locks."""

from scripts.ci import install_base_python_locks as installer


def test_reachable_index_missing_pin_is_deferable() -> None:
    """A reachable index proving newer versions exist may defer a stale pin."""

    output = (
        "ERROR: Could not find a version that satisfies the requirement "
        "pypdf==6.13.3 (from versions: 6.14.1, 6.14.2)\n"
        "ERROR: No matching distribution found for pypdf==6.13.3"
    )

    assert installer._is_deferable_preflight_failure(output)


def test_empty_index_missing_pin_remains_fatal() -> None:
    """An empty or unreachable package index must never be treated as optional."""

    output = (
        "ERROR: Could not find a version that satisfies the requirement "
        "pypdf==6.13.3 (from versions: none)\n"
        "ERROR: No matching distribution found for pypdf==6.13.3"
    )

    assert not installer._is_deferable_preflight_failure(output)
