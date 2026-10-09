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


def test_public_gateway_selection_rejects_private_unknown_and_missing_credentials(tmp_path):
    import os
    import subprocess
    import textwrap

    root = Path(__file__).resolve().parents[1]
    for filename, flag in (("noema-review.yml", "REQUIRE_ZDR"), ("opencode-review-dispatch.yml", "IS_PRIVATE")):
        text = (root / ".github" / "workflows" / filename).read_text()
        step = text.split("      - name: Select public review gateway\n", 1)[1].split("\n      - name:", 1)[0]
        command = textwrap.dedent(step.split("        run: |\n", 1)[1])
        for visibility, key, enabled in (("false", "test-placeholder", True), ("true", "test-placeholder", False), ("", "test-placeholder", False), ("false", "", False)):
            output = tmp_path / "output"
            output.write_text("")
            env = {**os.environ, flag: visibility, "LLM_GATEWAY_API_KEY": key, "GITHUB_OUTPUT": str(output)}
            subprocess.run(["bash", "-c", command], env=env, check=True, capture_output=True)
            assert output.read_text() == f"enabled={str(enabled).lower()}\n"


def test_opencode_gateway_config_keeps_reasoning_and_tools():
    import json
    import subprocess

    root = Path(__file__).resolve().parents[1]
    text = (root / ".github" / "workflows" / "opencode-review-dispatch.yml").read_text()
    start = text.index('            jq \'\n              .model = "contextual-orchestrator/auto"')
    jq_filter = text[start:].split("jq '", 1)[1].split("' ", 1)[0]
    original = {"provider": {"contextual-orchestrator": {"models": {"orchestrator/free": {"tool_call": True, "reasoning": True, "options": {"reasoningEffort": "high"}}}}}}
    completed = subprocess.run(["jq", jq_filter], input=json.dumps(original), text=True, capture_output=True, check=True)
    config = json.loads(completed.stdout)
    assert config["model"] == "contextual-orchestrator/auto"
    provider = config["provider"]["contextual-orchestrator"]
    assert provider["options"] == {"baseURL": "https://litellm.poinnetworks.net/v1", "apiKey": "{env:LLM_GATEWAY_API_KEY}"}
    assert provider["models"]["auto"]["tool_call"]
    assert provider["models"]["auto"]["options"]["reasoningEffort"] == "high"
