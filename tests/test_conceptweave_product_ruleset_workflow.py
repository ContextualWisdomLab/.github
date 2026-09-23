from pathlib import Path


WORKFLOW = Path(".github/workflows/conceptweave-product-ruleset-reconcile.yml")
MANIFEST = Path("config/conceptweave-product-ruleset.json")
RECONCILER = Path("scripts/ci/reconcile_conceptweave_product_ruleset.py")


def test_product_ruleset_workflow_keeps_mutation_manual_and_serialized() -> None:
    """Require privileged Product ruleset changes to stay manual and non-cancellable."""

    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "github.event_name == 'workflow_dispatch'" in text
    assert "github.ref == 'refs/heads/main'" in text
    assert "vars.CWL_RULESET_RECONCILE_ENABLED == 'true'" in text
    assert "environment: ruleset-governance-maintenance" in text
    assert "GH_TOKEN: ${{ secrets.CWL_RULESET_ADMIN_TOKEN }}" in text
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in text
    assert "if: github.event_name == 'workflow_dispatch' && inputs.mode == 'verify'" in text
    assert "github.event_name == 'push' ||" not in text


def test_product_ruleset_workflow_binds_admin_token_jobs_to_trusted_main_and_hardened_runner() -> None:
    """Never expose the ruleset admin credential from an arbitrary ref or unsupported runner."""

    text = WORKFLOW.read_text(encoding="utf-8")
    assert "if: github.event_name == 'workflow_dispatch' && inputs.mode == 'verify' && github.ref == 'refs/heads/main'" in text
    assert "runs-on: ubuntu-slim" not in text
    assert text.count("runs-on: ubuntu-24.04") == 3


def test_product_ruleset_workflow_pins_python_on_every_python_job() -> None:
    """Do not let privileged governance depend on incidental runner Python."""

    text = WORKFLOW.read_text(encoding="utf-8")
    setup = "uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0"
    assert text.count(setup) == 3
    assert text.count('python-version: "3.12"') == 3


def test_product_ruleset_workflow_uses_package_module_entrypoint() -> None:
    """Run package-qualified imports without PYTHONPATH or direct-script ambiguity."""

    text = WORKFLOW.read_text(encoding="utf-8")
    module = "python -m scripts.ci.reconcile_conceptweave_product_ruleset"
    assert text.count(module) == 5
    assert "python scripts/ci/reconcile_conceptweave_product_ruleset.py" not in text
    assert "PYTHONPATH" not in text


def test_product_ruleset_workflow_keeps_bootstrap_and_activation_distinct() -> None:
    """Keep evaluate creation separate from canary-gated active promotion."""

    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--mode bootstrap" in text
    assert "--mode activate" in text
    assert "--canary-pr \"$CANARY_PR\"" in text
    assert "--canary-run-id \"$CANARY_RUN_ID\"" in text
    assert "- name: Verify active post-change live state\n        if: inputs.mode == 'activate'" in text
    assert "- name: Verify post-change live state" not in text


def test_product_ruleset_manifest_starts_unadopted() -> None:
    """Initial source must not guess the absent organization ruleset identity."""

    text = MANIFEST.read_text(encoding="utf-8")
    assert '"ruleset_id": null' in text


def test_product_gate_is_workflow_bound_and_conceptweave_scoped() -> None:
    """Reject same-App/check-name enforcement in favor of an exact workflow rule."""

    text = RECONCILER.read_text(encoding="utf-8")
    assert "TARGET_REPOSITORY_ID = 1353201939" in text
    assert 'scope="organization"' in text
    assert 'f"orgs/{ORGANIZATION}/rulesets"' in text
    assert '"repository_id": {"repository_ids": [TARGET_REPOSITORY_ID]}' in text
    assert '"type": "workflows"' in text
    assert '"repository_id": TARGET_REPOSITORY_ID' in text
    assert '"path": PRODUCT_WORKFLOW_PATH' in text
    assert '"ref": f"refs/heads/{TARGET_BRANCH}"' in text
    assert '"required_status_checks"' not in text
    assert "integration_id" not in text
