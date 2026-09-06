"""External bootstrap admission stays closed until a released adapter exists."""

import importlib
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


def gateway_module():
    """Load the owner port without importing a proposed CO implementation."""
    return importlib.import_module("scripts.ci.external_review_gateway")


def gateway_configuration(tmp_path):
    """Create a private test credential file, never a provider credential."""
    token_file = tmp_path / "gateway.token"
    token_file.write_text("unit-test-gateway-credential")
    token_file.chmod(0o600)
    return gateway_module().ExternalGatewayConfig(
        base_url="https://gateway.example.invalid",
        token_file=token_file,
        require_zdr=True,
    )


def test_unreleased_external_mode_fails_before_provider_secret_bootstrap(tmp_path):
    """Opt-in must not fall back to local provider bootstrap or export readiness."""
    output_file = tmp_path / "github-env"
    command_result = subprocess.run(
        ["bash", "scripts/ci/contextual_orchestrator_review_sidecar.sh"],
        env={
            "PATH": os.environ["PATH"],
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_ENV": str(output_file),
            "CONTEXTUAL_ORCHESTRATOR_GATEWAY_MODE": "external",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert command_result.returncode == 1
    assert (
        "released_contract_unavailable" in command_result.stdout + command_result.stderr
    )
    assert "provider secrets" not in command_result.stdout + command_result.stderr
    assert not output_file.exists()


@pytest.mark.parametrize(
    "base_url",
    [
        "http://gateway.invalid",
        "https://user@gateway.invalid",
        "https://gateway.invalid/path",
        "https://gateway.invalid?token=value",
        "https://gateway.invalid/#fragment",
        "https://gateway.invalid\n",
    ],
)
def test_external_origin_rejects_ambiguous_or_insecure_configuration(
    tmp_path, base_url
):
    """No HTTP, credentials, path, query, fragment or control-byte origin is valid."""
    gateway_config = gateway_configuration(tmp_path)
    gateway_config.base_url = base_url
    with pytest.raises(gateway_module().GatewayAdmissionError):
        gateway_config.validate()


def test_external_credentials_must_be_private_regular_owned_files(tmp_path):
    """A world-readable or symlink credential cannot reach a probe adapter."""
    gateway_config = gateway_configuration(tmp_path)
    gateway_config.token_file.chmod(0o644)
    with pytest.raises(gateway_module().GatewayAdmissionError):
        gateway_config.validate()
    gateway_config.token_file.chmod(0o600)
    token_link = tmp_path / "token-link"
    token_link.symlink_to(gateway_config.token_file)
    gateway_config.token_file = token_link
    with pytest.raises(gateway_module().GatewayAdmissionError):
        gateway_config.validate()


@pytest.mark.parametrize(
    "missing_capability", ["inventory", "json_object", "json_schema", "tool_call"]
)
def test_probe_failure_never_exports_partial_readiness(tmp_path, missing_capability):
    """Every required inference capability is part of one fail-closed result."""
    gateway_config = gateway_configuration(tmp_path)
    probe_calls = []

    def probe_capability(capability_name, *, model_name, require_zdr):
        probe_calls.append((capability_name, model_name, require_zdr))
        return capability_name != missing_capability

    probe_port = SimpleNamespace(
        list_models=lambda: (
            [] if missing_capability == "inventory" else ["orchestrator/free"]
        ),
        probe_capability=probe_capability,
    )
    with pytest.raises(gateway_module().GatewayAdmissionError):
        gateway_module().verify_external_gateway(gateway_config, probe_port)
    assert all(
        model_name == "orchestrator/free" and require_zdr is True
        for _, model_name, require_zdr in probe_calls
    )


def test_probe_success_reports_only_safe_inference_evidence(tmp_path):
    """A port test double cannot inject raw payload or credential evidence."""
    probe_port = SimpleNamespace(
        list_models=lambda: ["orchestrator/free"],
        probe_capability=lambda *args, **kwargs: True,
    )
    evidence = gateway_module().verify_external_gateway(
        gateway_configuration(tmp_path), probe_port
    )
    assert evidence["model"] == "orchestrator/free"
    assert evidence["private_requests_require_zdr"] is True
    assert evidence["capabilities"] == {
        "json_object": "passed",
        "json_schema": "passed",
        "tool_call": "passed",
    }
    assert "credential" not in json.dumps(evidence)
    assert gateway_module().RELEASED_GATEWAY_ADAPTERS == {}


@pytest.mark.parametrize(
    "model_inventory",
    ["orchestrator/free", {"orchestrator/free": True}, ["orchestrator/free", None]],
)
def test_malformed_inventory_cannot_satisfy_admission(tmp_path, model_inventory):
    """Do not interpret substring or dictionary membership as a model list."""
    probe_port = SimpleNamespace(
        list_models=lambda: model_inventory,
        probe_capability=lambda *args, **kwargs: True,
    )
    with pytest.raises(gateway_module().GatewayAdmissionError):
        gateway_module().verify_external_gateway(
            gateway_configuration(tmp_path), probe_port
        )


def test_bootstrap_action_defaults_to_existing_sidecar():
    """Only an explicit mode input admits the future external bootstrap."""
    action_source = Path(
        ".github/actions/orchestrator-free-sidecar/action.yml"
    ).read_text()
    assert 'default: "sidecar"' in action_source
    assert (
        "CONTEXTUAL_ORCHESTRATOR_GATEWAY_MODE: ${{ inputs.gateway_mode }}"
        in action_source
    )
    assert "inputs.gateway_token_file" in action_source


def test_unverified_revision_never_constructs_an_adapter(monkeypatch, capsys):
    """An arbitrary full SHA is not release authorization."""
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_GATEWAY_CONTRACT_REVISION", "a" * 40)
    assert gateway_module().main() == 1
    assert "released_contract_unavailable" in capsys.readouterr().out


def test_registered_port_test_double_exports_only_file_paths(
    tmp_path, monkeypatch, capsys
):
    """Exercise future publication with an in-memory owner test double only."""
    module = gateway_module()
    gateway_config = gateway_configuration(tmp_path)
    output_file = tmp_path / "github-env"
    probe_port = SimpleNamespace(
        list_models=lambda: ["orchestrator/free"],
        probe_capability=lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        module,
        "RELEASED_GATEWAY_ADAPTERS",
        {"test_double_revision": lambda config: probe_port},
    )
    for variable_name, variable_value in {
        "CONTEXTUAL_ORCHESTRATOR_GATEWAY_CONTRACT_REVISION": "test_double_revision",
        "CONTEXTUAL_ORCHESTRATOR_BASE_URL": gateway_config.base_url,
        "CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE": str(gateway_config.token_file),
        "CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR": "true",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_ENV": str(output_file),
    }.items():
        monkeypatch.setenv(variable_name, variable_value)
    assert module.main() == 0
    output_text = output_file.read_text() + capsys.readouterr().out
    assert "unit-test-gateway-credential" not in output_text
    assert "CONTEXTUAL_ORCHESTRATOR_PRIVATE_REQUESTS_REQUIRE_ZDR=true" in output_text
    assert "CONTEXTUAL_ORCHESTRATOR_TOKEN=" not in output_text
    evidence_files = list(tmp_path.glob("external-review-*/preflight-evidence.json"))
    assert len(evidence_files) == 1
    assert "unit-test-gateway-credential" not in evidence_files[0].read_text()


def test_adapter_exception_is_sanitized_without_readiness(
    tmp_path, monkeypatch, capsys
):
    """Raw adapter failures cannot become output, evidence, or a fallback."""
    module = gateway_module()
    gateway_config = gateway_configuration(tmp_path)

    def failing_adapter(config):
        raise RuntimeError("private-upstream-body-with-secret")

    monkeypatch.setattr(
        module, "RELEASED_GATEWAY_ADAPTERS", {"test_double_revision": failing_adapter}
    )
    monkeypatch.setenv(
        "CONTEXTUAL_ORCHESTRATOR_GATEWAY_CONTRACT_REVISION", "test_double_revision"
    )
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_BASE_URL", gateway_config.base_url)
    monkeypatch.setenv(
        "CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE", str(gateway_config.token_file)
    )
    assert module.main() == 1
    output_text = capsys.readouterr().out
    assert "private-upstream" not in output_text
    assert "external_gateway_admission_failed" in output_text
