"""Contract for the reusable R-CMD-check workflow.

Replaces kaefa's and nonnest2's near-identical, hand-copied
``R-CMD-check.yaml`` files with one reusable ``workflow_call`` workflow,
``.github/workflows/r-package-check.yml``, plus a thin caller left in each
product repository. See
``docs/doctoring/r-cmd-check-reusable-workflow-consolidation.md`` and
``docs/adr/0023-r-cmd-check-reusable-workflow-consolidation.md`` for why.
"""

from __future__ import annotations

from pathlib import Path

_WORKFLOW = Path(".github/workflows/r-package-check.yml")

_R_LIB_PIN = "6f6e5bc62fba3a704f74e7ad7ef7676c5c6a2590"
_CHECKOUT_PIN = "3d3c42e5aac5ba805825da76410c181273ba90b1"


def _workflow_text() -> str:
    """Read the reusable R-CMD-check workflow as UTF-8 text."""
    return _WORKFLOW.read_text(encoding="utf-8")


def test_declares_workflow_call_with_six_inputs_and_recorded_defaults() -> None:
    """Every genuinely varying caller field is data, never executable shell source."""
    workflow = _workflow_text()
    assert "on:\n  workflow_call:\n    inputs:" in workflow
    for name in (
        "r_matrix:",
        "needs_tinytex:",
        "extra_packages:",
        "check_args:",
        "install_package_before_pre_check:",
        "pre_check_test_file:",
    ):
        assert name in workflow

    assert 'default: \'[{"os": "ubuntu-latest", "r": "release"}]\'' in workflow
    assert workflow.count("default: false") >= 2
    assert 'default: "any::rcmdcheck"' in workflow
    assert "default: 'c(\"--no-manual\", \"--as-cran\")'" in workflow
    assert 'default: ""' in workflow


def test_step_order_matches_the_r_lib_template_sequence() -> None:
    """checkout -> pandoc -> [tinytex] -> setup-r -> deps -> bounded pre-check -> check."""
    workflow = _workflow_text()
    order = [
        "actions/checkout@",
        "r-lib/actions/setup-pandoc@",
        "r-lib/actions/setup-tinytex@",
        "r-lib/actions/setup-r@",
        "r-lib/actions/setup-r-dependencies@",
        "Install package for bounded pre-check",
        "Run bounded testthat pre-check",
        "r-lib/actions/check-r-package@",
    ]
    positions = [workflow.index(marker) for marker in order]
    assert positions == sorted(positions), "steps are out of order"


def test_optional_steps_are_gated_on_bounded_inputs() -> None:
    """Optional setup and pre-check steps run only for explicit bounded capabilities."""
    workflow = _workflow_text()
    assert (
        "- if: inputs.needs_tinytex\n        uses: r-lib/actions/setup-tinytex@"
        in workflow
    )
    assert (
        "- if: inputs.pre_check_test_file != '' && inputs.install_package_before_pre_check\n"
        "        name: Install package for bounded pre-check"
        in workflow
    )
    assert (
        "- if: inputs.pre_check_test_file != ''\n"
        "        name: Run bounded testthat pre-check"
        in workflow
    )
    assert "PRE_CHECK_TEST_FILE: ${{ inputs.pre_check_test_file }}" in workflow
    assert 'testthat::test_file(Sys.getenv("PRE_CHECK_TEST_FILE"))' in workflow


def test_action_pins_are_uniform_and_current() -> None:
    """Every r-lib step and checkout share one current pin, not per-caller drift."""
    workflow = _workflow_text()
    assert workflow.count(_R_LIB_PIN) == 5  # pandoc, tinytex, setup-r, deps, check
    assert f"actions/checkout@{_CHECKOUT_PIN}" in workflow
    assert f"r-lib/actions/setup-pandoc@{_R_LIB_PIN}" in workflow
    assert f"r-lib/actions/setup-tinytex@{_R_LIB_PIN}" in workflow
    assert f"r-lib/actions/setup-r@{_R_LIB_PIN}" in workflow
    assert f"r-lib/actions/setup-r-dependencies@{_R_LIB_PIN}" in workflow
    assert f"r-lib/actions/check-r-package@{_R_LIB_PIN}" in workflow


def test_uniform_fields_are_hardcoded_not_parameterized() -> None:
    """Fields byte-identical across both originals stay static, not inputs."""
    workflow = _workflow_text()
    assert "permissions:\n  contents: read" in workflow
    assert "GITHUB_PAT: ${{ secrets.GITHUB_TOKEN }}" in workflow
    assert "R_KEEP_PKG_SOURCE: yes" in workflow
    assert "build_args: 'c(\"--no-manual\")'" in workflow
    assert "error-on: '\"error\"'" in workflow
    assert "upload-snapshots: true" in workflow
    assert "args: ${{ inputs.check_args }}" in workflow
    assert "extra-packages: ${{ inputs.extra_packages }}" in workflow


def test_matrix_is_driven_by_the_r_matrix_input() -> None:
    """The strategy matrix must come from fromJSON(inputs.r_matrix), not a fixed list."""
    workflow = _workflow_text()
    assert "config: ${{ fromJSON(inputs.r_matrix) }}" in workflow
    assert "runs-on: ${{ matrix.config.os }}" in workflow
    assert "r-version: ${{ matrix.config.r }}" in workflow
    assert "http-user-agent: ${{ matrix.config['http-user-agent'] }}" in workflow


def test_pre_check_hook_is_bounded_data_not_caller_shell_source() -> None:
    """A reusable caller must not inject arbitrary Bash source into the trusted job."""
    workflow = _workflow_text()
    assert "pre_check_script:" not in workflow
    assert "run: ${{ inputs.pre_check_script }}" not in workflow
    assert "pre_check_test_file:" in workflow
    assert "install_package_before_pre_check:" in workflow
    assert "PRE_CHECK_TEST_FILE: ${{ inputs.pre_check_test_file }}" in workflow
    assert 'case "$PRE_CHECK_TEST_FILE" in' in workflow
    assert "tests/testthat/*.R" in workflow
    assert '"$PRE_CHECK_TEST_FILE" == *".."*' in workflow
    assert '"$PRE_CHECK_TEST_FILE" == /*' in workflow
    assert 'testthat::test_file(Sys.getenv("PRE_CHECK_TEST_FILE"))' in workflow
