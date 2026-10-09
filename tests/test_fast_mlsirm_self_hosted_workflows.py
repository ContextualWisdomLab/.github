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


def test_noema_uses_litellm_auto_for_public_reviews_and_keeps_private_sidecar():
    root = Path(__file__).resolve().parents[1]
    text = (root / ".github" / "workflows" / "noema-review.yml").read_text()
    assert "https://litellm.poinnetworks.net/v1/chat/completions" in text
    assert 'export NOEMA_LLM_MODEL="auto"' in text
    assert "secrets.LLM_GATEWAY_API_KEY" in text
    assert "Private targets retain the verified ZDR sidecar route." in text
    assert "steps.llm_gateway.outputs.enabled != 'true'" in text
