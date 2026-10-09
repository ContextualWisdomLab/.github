from pathlib import Path


def test_fast_mlsirm_reusable_workflows_keep_isolated_runner_and_gate_contracts():
    root = Path(__file__).resolve().parents[1]
    workflows = root / ".github" / "workflows"
    for name in ("ci", "codeql", "statistical-studies", "hourly-pr-governance", "pypi-gap-guard"):
        text = (workflows / f"fast-mlsirm-{name}.yml").read_text()
        assert "workflow_call:" in text
        assert "ubuntu-latest" not in text and "runs-on: ubuntu" not in text
        assert "group: CWL CI isolated" in text
        assert "labels: [self-hosted, Linux, X64]" in text
        assert f"group: central-fast-mlsirm-{name}-" in text
    ci = (workflows / "fast-mlsirm-ci.yml").read_text()
    assert 'python-version: ["3.12", "3.14"]' in ci
    assert 'test "${{ needs.python-matrix.result }}" = "success"' in ci
    assert "cargo test --locked --workspace" in ci
    assert "cargo test --locked --manifest-path crates/fast-mlsirm-py/Cargo.toml" in ci
def test_hosted_only_release_legs_are_disabled_without_partial_publication():
    import yaml
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / '.github/workflows/fast-mlsirm-publish-pypi.yml').read_text())
    jobs = workflow['jobs']
    assert jobs['wheels']['if'] == '${{ false }}'
    assert jobs['macos-x86-runtime']['if'] == '${{ false }}'
    assert 'macos-x86-runtime' in jobs['reproducibility-record']['needs']
    assert 'reproducibility-record' in jobs['publish-pypi']['needs']
    assert 'release-admission' in jobs['publish-pypi']['needs']
    assert 'if' not in jobs['publish-pypi']
