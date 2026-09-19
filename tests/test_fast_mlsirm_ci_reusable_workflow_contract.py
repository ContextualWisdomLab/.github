"""Contract for the reusable fast-mlsirm product CI workflow.

``.github/workflows/fast-mlsirm-ci.yml`` centralizes the maturin/PyO3, Rust
workspace, software-Vulkan GPU, Atheris, and wheel-acceptance job bodies that
previously existed only in ``ContextualWisdomLab/fast-mlsirm``. See
``docs/doctoring/fast-mlsirm-ci-reusable-workflow-consolidation.md``.

Two properties this file exists to defend:

* It is a callable library, never a required workflow. Required-workflow
  admission scans the whole file, and this one builds and executes product
  code (ADR 0025 records what that costs when violated).
* It adds no name-preserving stub jobs. A caller job that only ``uses:`` this
  workflow consumes no runner, so the consumer's job count per PR head is
  unchanged under the plan concurrency ceiling (ADR 0030).
"""

from __future__ import annotations

from pathlib import Path

import yaml

_WORKFLOW = Path(".github/workflows/fast-mlsirm-ci.yml")
_CHECKOUT_PIN = "3d3c42e5aac5ba805825da76410c181273ba90b1"
_SETUP_PYTHON_PIN = "5fda3b95a4ea91299a34e894583c3862153e4b97"
_RUST_TOOLCHAIN_PIN = "4be7066ada62dd38de10e7b70166bc74ed198c30"


def _workflow_text() -> str:
    """Read the reusable fast-mlsirm CI workflow as UTF-8 text."""
    return _WORKFLOW.read_text(encoding="utf-8")


def _workflow() -> dict:
    """Parse the reusable workflow into a mapping."""
    return yaml.safe_load(_workflow_text())


def test_is_callable_only_and_never_event_triggered() -> None:
    """A required-workflow ruleset must never be able to admit this file."""
    triggers = _workflow()[True]
    assert set(triggers) == {"workflow_call"}


def test_declares_bounded_data_inputs_with_recorded_defaults() -> None:
    """Every varying caller field is data or a capability flag, never shell source."""
    inputs = _workflow()[True]["workflow_call"]["inputs"]
    assert set(inputs) == {
        "python-versions",
        "rust-toolchain",
        "run-gpu-smoke",
        "run-fuzz",
        "run-package",
    }
    assert inputs["python-versions"]["default"] == '["3.12", "3.14"]'
    assert inputs["rust-toolchain"]["default"] == "1.97.1"
    for flag in ("run-gpu-smoke", "run-fuzz", "run-package"):
        assert inputs[flag]["type"] == "boolean"
        assert inputs[flag]["default"] is True
    for name, spec in inputs.items():
        assert spec["type"] in {"string", "boolean"}, name


def test_no_input_reaches_a_run_step_as_shell() -> None:
    """Inputs may parameterize `with:` and `if:`, never a `run:` body."""
    for job in _workflow()["jobs"].values():
        for step in job.get("steps", []):
            assert "inputs." not in step.get("run", "")


def test_publishes_the_product_lanes() -> None:
    """The consumer's lanes stay one-to-one so check contexts remain predictable."""
    assert set(_workflow()["jobs"]) == {
        "python-matrix",
        "rust",
        "gpu-smoke",
        "fuzz",
        "package",
    }


def test_carries_no_needs_edge() -> None:
    """Every lane is independent, so none of them pays a second queue wait.

    docs/doctoring/actions-capacity-root-cause-20260917.md measured inter-job
    queue wait at 97.5% of one run's wall time, compounding once per `needs:`
    edge under the org concurrency ceiling. An aggregate job re-exporting the
    matrix under a single stable name would reintroduce exactly that edge for
    an `echo`; the consumer requires the matrix legs directly instead.
    """
    for name, job in _workflow()["jobs"].items():
        assert "needs" not in job, name


def test_optional_lanes_are_gated_on_their_capability_input() -> None:
    """Skipping a lane is a caller decision, not an edit here."""
    jobs = _workflow()["jobs"]
    assert jobs["gpu-smoke"]["if"] == "${{ inputs.run-gpu-smoke }}"
    assert jobs["fuzz"]["if"] == "${{ inputs.run-fuzz }}"
    assert jobs["package"]["if"] == "${{ inputs.run-package }}"


def test_every_third_party_action_is_pinned_to_a_commit_sha() -> None:
    """Mutable tags are forbidden in a workflow every consumer inherits."""
    workflow = _workflow_text()
    assert f"actions/checkout@{_CHECKOUT_PIN}" in workflow
    assert f"actions/setup-python@{_SETUP_PYTHON_PIN}" in workflow
    assert f"dtolnay/rust-toolchain@{_RUST_TOOLCHAIN_PIN}" in workflow
    for line in workflow.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("- uses:", "uses:")):
            continue
        _, _, reference = stripped.partition("uses:")
        _, _, version = reference.strip().partition("@")
        assert len(version) == 40 and all(
            character in "0123456789abcdef" for character in version
        ), stripped


def test_every_checkout_disables_persisted_credentials() -> None:
    """Untrusted product builds must not receive a checkout-persisted token."""
    checkout_steps = [
        step
        for job in _workflow()["jobs"].values()
        for step in job.get("steps", [])
        if step.get("uses") == f"actions/checkout@{_CHECKOUT_PIN}"
    ]
    assert len(checkout_steps) == 5
    for step in checkout_steps:
        assert step.get("with", {}).get("persist-credentials") is False


def test_fuzz_dependencies_are_hash_locked_before_local_install() -> None:
    """The fuzz lane resolves no registry dependency outside a hash lock."""
    run_steps = [
        step["run"]
        for step in _workflow()["jobs"]["fuzz"]["steps"]
        if "run" in step
    ]
    assert (
        "python -m pip install --require-hashes -r requirements/fuzz.txt"
        in run_steps
    )
    assert (
        "python -m pip install --no-deps --no-build-isolation -e ."
        in run_steps
    )
    assert not any("pip install --upgrade" in command for command in run_steps)
    assert not any(".[fuzz]" in command for command in run_steps)


def test_gpu_lane_refuses_skipped_evidence() -> None:
    """A skipped GPU test is absence of evidence, not passing evidence."""
    steps = _workflow()["jobs"]["gpu-smoke"]["steps"]
    guard = [step for step in steps if step.get("name") == "Reject skipped GPU evidence"]
    assert guard, "gpu-smoke lost its skip guard"
    assert "GPU evidence contained" in guard[0]["run"]


def test_package_lane_keeps_the_rust_required_acceptance_contract() -> None:
    """The wheel must carry the compiled core and pass the release gates."""
    workflow = _workflow_text()
    assert "scripts/release_acceptance.py --out release-acceptance --require-rust" in workflow
    assert "scripts/sales_readiness.py" in workflow
    assert "--require-rust" in workflow
    assert "--check-import" in workflow


def test_declares_least_privilege_permissions() -> None:
    """A called workflow cannot elevate the caller token; declare the floor anyway."""
    assert _workflow()["permissions"] == {"contents": "read"}
