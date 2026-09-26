"""Regression contract for Strix trusted-runtime fixture isolation."""

from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = REPOSITORY_ROOT / "scripts" / "ci" / "test_strix_quick_gate.sh"
CONSUMER_ROOT_MATERIALIZATION = (
    'materialize_trusted_gate_fixture "$repo_root_dir/scripts/ci"'
)


def _consumer_root_materialization_owners(source: str) -> tuple[str, ...]:
    """Return shell-function names that install trusted runtime in the consumer."""
    owners: list[str] = []
    current_function = "<top-level>"
    for raw_line in source.splitlines():
        stripped = raw_line.strip()
        if stripped.endswith("() {"):
            current_function = stripped.removesuffix("() {").strip()
        if CONSUMER_ROOT_MATERIALIZATION in raw_line:
            owners.append(current_function)
    return tuple(owners)


def test_specialized_strix_fixtures_keep_trusted_runtime_outside_consumer() -> None:
    """Fail while any fixture can mask consumer-root binder resolution."""
    source = HARNESS_PATH.read_text(encoding="utf-8")
    offenders = _consumer_root_materialization_owners(source)

    assert not offenders, (
        "trusted Strix gate/model/binder must be materialized outside "
        "repo_root_dir; consumer-root materialization remains in: "
        + ", ".join(offenders)
    )
