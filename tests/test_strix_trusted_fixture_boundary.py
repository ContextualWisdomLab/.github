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
        if (CONSUMER_ROOT_MATERIALIZATION in raw_line
                or ('cp "$GATE_SCRIPT" "$repo_root_dir/scripts/ci/strix_quick_gate.sh"' in raw_line
                    and current_function != "run_gate_case")):
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


def test_base_fixture_executes_trusted_runtime_when_consumer_source_is_retained() -> None:
    """A source file under scan must never select the runtime being executed."""
    source = HARNESS_PATH.read_text(encoding="utf-8")
    fixture = source.split("\nrun_gate_case() {", 1)[1].split(
        "\nrun_gate_case_with_provider_signal_mode() {", 1)[0]
    assert 'local gate_under_test="$trusted_script_dir/strix_quick_gate.sh"' in fixture
    assert 'materialize_trusted_gate_fixture "$trusted_script_dir"' in fixture
    assert 'STRIX_REPO_ROOT="$repo_root_dir" bash "$gate_under_test"' in fixture
    assert 'bash "./scripts/ci/strix_quick_gate.sh"' not in fixture
