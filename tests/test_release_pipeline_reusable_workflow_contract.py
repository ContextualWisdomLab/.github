"""Contract for the reusable release-tag and publish-package workflows.

Centralises the provenance-gated release cut and package publication that
fast-mlsirm previously carried as standalone ``release-tag.yml`` /
``publish-pypi.yml`` files. See
``docs/doctoring/release-pipeline-reusable-workflows.md`` and
``docs/adr/0032-release-pipeline-reusable-workflows.md``.
"""

from __future__ import annotations

from pathlib import Path

_RELEASE_TAG = Path(".github/workflows/release-tag.yml")
_PUBLISH_PACKAGE = Path(".github/workflows/publish-package.yml")
_DOCTORING = Path("docs/doctoring/release-pipeline-reusable-workflows.md")
_ADR_0032 = Path("docs/adr/0032-release-pipeline-reusable-workflows.md")

_CHECKOUT_PIN = "3d3c42e5aac5ba805825da76410c181273ba90b1"
_SETUP_PYTHON_PIN = "5fda3b95a4ea91299a34e894583c3862153e4b97"
_MATURIN_PIN = "e83996d129638aa358a18fbd1dfb82f0b0fb5d3b"
_UPLOAD_ARTIFACT_PIN = "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
_DOWNLOAD_ARTIFACT_PIN = "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"
_PYPI_PUBLISH_PIN = "dc37677b2e1c63e2034f94d8a5b11f265b73ba33"

_RELEASE_TAG_USES_PIN = (
    "uses: ContextualWisdomLab/.github/.github/workflows/release-tag.yml@<sha>"
)
_PUBLISH_PACKAGE_USES_PIN = (
    "uses: ContextualWisdomLab/.github/.github/workflows/publish-package.yml@<sha>"
)

# Active-YAML event triggers that must never appear on the reusable targets.
# Product repos own workflow_dispatch (and any branch restriction) in thin
# callers; pull_request/push would turn the central files into org-wide
# accidental triggers once ruleset-injected.
_FORBIDDEN_DIRECT_TRIGGERS = (
    "workflow_dispatch:",
    "pull_request:",
    "pull_request_target:",
    "push:",
)


def _release_text() -> str:
    """Read the reusable release-tag workflow as UTF-8 text."""
    return _RELEASE_TAG.read_text(encoding="utf-8")


def _publish_text() -> str:
    """Read the reusable publish-package workflow as UTF-8 text."""
    return _PUBLISH_PACKAGE.read_text(encoding="utf-8")


def _doctoring_text() -> str:
    """Read the release-pipeline sibling-caller doctoring note as UTF-8 text."""
    return _DOCTORING.read_text(encoding="utf-8")


def _adr_0032_text() -> str:
    """Read ADR-0032 as UTF-8 text."""
    return _ADR_0032.read_text(encoding="utf-8")


def _active_yaml(workflow: str) -> str:
    """Strip comment-only lines so header example callers cannot false-positive."""
    return "\n".join(
        line for line in workflow.splitlines() if not line.lstrip().startswith("#")
    )


def _assert_workflow_call_only(workflow: str) -> None:
    """Require workflow_call and forbid direct PR/push/dispatch triggers."""
    assert "on:\n  workflow_call:\n    inputs:" in workflow
    active = _active_yaml(workflow)
    for trigger in _FORBIDDEN_DIRECT_TRIGGERS:
        assert trigger not in active, trigger


def test_release_tag_is_workflow_call_only() -> None:
    """Product repos keep workflow_dispatch; central file has no PR/push triggers."""
    _assert_workflow_call_only(_release_text())


def test_release_tag_declares_required_version_and_commit_inputs() -> None:
    """release_commit is required; release_version is optional under Noema."""
    workflow = _release_text()
    for name in (
        "release_version:",
        "release_commit:",
        "decide_version_with_noema:",
        "central_workflows_ref:",
        "publish_workflow:",
        "run_changelog_fragment_check:",
        "pyproject_path:",
        "changelog_path:",
    ):
        assert name in workflow
    assert 'default: "publish-pypi.yml"' in workflow
    assert "decide_version_with_noema:" in workflow
    assert "noema_semver_bump.py" in workflow


def test_release_tag_keeps_fail_closed_provenance_checks() -> None:
    """Every provenance gate from the fast-mlsirm original remains."""
    workflow = _release_text()
    markers = [
        "release dispatch must target",
        "release_commit must be a canonical 40-character lowercase SHA-1",
        "release commit must be an ancestor of the default branch",
        "expected exactly one CHANGELOG section",
        "parent project version already equals requested release version",
        "parent CHANGELOG already contains requested release section",
        "render_changelog_fragments.py --check",
        "release-body limit",
        "refusing to overwrite or reuse it",
        "resume_existing_tag",
        "gh release create",
        "--verify-tag",
        "--notes-file release_notes.md",
        "Noema semver",
    ]
    for marker in markers:
        assert marker in workflow, marker


def test_release_tag_action_pins_match_release_validated_set() -> None:
    """Checkout pin stays the release-validated SHA, not an unpinned tag."""
    workflow = _release_text()
    assert f"actions/checkout@{_CHECKOUT_PIN}" in workflow


def test_release_tag_dispatch_of_publish_is_skippable() -> None:
    """Empty publish_workflow skips package dispatch (GitHub release only)."""
    workflow = _release_text()
    assert "if: inputs.publish_workflow != ''" in workflow
    assert 'gh workflow run "$PUBLISH_WORKFLOW"' in workflow


def test_publish_package_is_workflow_call_only() -> None:
    """Publication is also a reusable target; no PR/push/dispatch on the central file."""
    _assert_workflow_call_only(_publish_text())


def test_sibling_caller_pin_contract_documents_uses_and_noema_gate() -> None:
    """Doctoring + ADR-0032 record the exact pin pattern and Noema bump inputs.

    Product repos adopt after merge by copying these pin fields; the contract
    fails if the durable adoption surface drifts away from the reusable
    workflow inputs.
    """
    doctoring = _doctoring_text()
    adr = _adr_0032_text()
    assert "## Sibling-caller pin contract" in doctoring
    assert _RELEASE_TAG_USES_PIN in doctoring
    assert _PUBLISH_PACKAGE_USES_PIN in doctoring
    for pin_field in (
        "central_workflows_ref",
        "decide_version_with_noema",
        "release_commit",
        "NOEMA_LLM_API_KEY",
        "control_plane_commit",
        "packaging_backend",
    ):
        assert pin_field in doctoring, pin_field
    assert "Never `@main`" in doctoring or "never `@main`" in doctoring.lower()
    assert "workflow_call" in doctoring
    assert "pull_request" in doctoring and "push" in doctoring
    assert _RELEASE_TAG_USES_PIN in adr
    assert _PUBLISH_PACKAGE_USES_PIN in adr
    assert "central_workflows_ref" in adr
    assert "Noema bump gate" in adr or "Noema" in adr


def test_publish_package_declares_backend_and_pypi_inputs() -> None:
    """packaging_backend and publish_to_pypi are the per-repo policy knobs."""
    workflow = _publish_text()
    for name in (
        "release_tag:",
        "release_commit:",
        "control_plane_commit:",
        "packaging_backend:",
        "publish_to_pypi:",
        "pypi_environment:",
        "maturin_version:",
        "ensure_sdist_license:",
    ):
        assert name in workflow
    assert 'default: "maturin"' in workflow
    assert 'default: "pypi"' in workflow


def test_publish_package_rejects_unknown_packaging_backend() -> None:
    """Fail closed when a caller passes an unsupported backend string."""
    workflow = _publish_text()
    assert "maturin|pure-python" in workflow
    assert "packaging_backend must be maturin or pure-python" in workflow


def test_publish_package_keeps_control_plane_and_tag_provenance() -> None:
    """Control-plane SHA, default-branch ref, and tag→commit binding stay fail-closed."""
    workflow = _publish_text()
    markers = [
        "control_plane_commit must be a canonical 40-character lowercase SHA-1",
        "package publication must run from",
        "publication control plane moved after release verification",
        "release tag does not target release_commit",
        "release tag does not match project version",
    ]
    for marker in markers:
        assert marker in workflow, marker


def test_publish_package_maturin_and_pure_python_jobs_are_mutually_gated() -> None:
    """Maturin sdist/wheels and pure-python build never both run for one call."""
    workflow = _publish_text()
    assert "if: inputs.packaging_backend == 'maturin'" in workflow
    assert "if: inputs.packaging_backend == 'pure-python'" in workflow
    assert "python -m build --outdir dist" in workflow
    assert "PyO3/maturin-action@" in workflow


def test_publish_package_action_pins_match_release_validated_set() -> None:
    """Every third-party action keeps the SHA that fast-mlsirm release-validated."""
    workflow = _publish_text()
    assert f"actions/checkout@{_CHECKOUT_PIN}" in workflow
    assert f"actions/setup-python@{_SETUP_PYTHON_PIN}" in workflow
    assert f"PyO3/maturin-action@{_MATURIN_PIN}" in workflow
    assert f"actions/upload-artifact@{_UPLOAD_ARTIFACT_PIN}" in workflow
    assert f"actions/download-artifact@{_DOWNLOAD_ARTIFACT_PIN}" in workflow
    assert f"pypa/gh-action-pypi-publish@{_PYPI_PUBLISH_PIN}" in workflow


def test_publish_package_pypi_job_uses_environment_and_oidc() -> None:
    """Trusted publishing needs the pypi environment plus id-token: write."""
    workflow = _publish_text()
    assert "environment: ${{ inputs.pypi_environment }}" in workflow
    assert "id-token: write" in workflow
    assert "inputs.publish_to_pypi" in workflow
    assert "skip-existing: true" in workflow
    assert "PIPY_TOKEN" in workflow


def test_publish_package_skips_immutable_release_asset_upload() -> None:
    """Immutable GitHub Releases must not fail a PyPI-only republish."""
    workflow = _publish_text()
    assert "release $RELEASE_TAG is immutable; skipping GitHub asset upload" in workflow
    assert ".immutable // false" in workflow
