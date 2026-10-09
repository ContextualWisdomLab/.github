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


def test_relative_token_reference_cannot_cross_step_boundaries(tmp_path, monkeypatch):
    """Later steps may change working directory; token paths must be absolute."""
    gateway_config = gateway_configuration(tmp_path)
    gateway_config.token_file = Path("gateway.token")
    monkeypatch.chdir(tmp_path)
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
        return gateway_module().ProbeReceipt(
            capability_name,
            200,
            gateway_module().ProbeErrorCategory.CAPABILITY_UNAVAILABLE
            if capability_name == missing_capability
            else None,
        )

    probe_port = SimpleNamespace(
        list_models=lambda: gateway_module().ProbeReceipt(
            "discovery",
            200,
            gateway_module().ProbeErrorCategory.POLICY_UNAVAILABLE
            if missing_capability == "inventory"
            else None,
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
        list_models=lambda: gateway_module().ProbeReceipt("discovery", 200),
        probe_capability=lambda name, **kwargs: gateway_module().ProbeReceipt(
            name, 200
        ),
    )
    evidence = gateway_module().verify_external_gateway(
        gateway_configuration(tmp_path), probe_port
    )
    assert evidence["requested_model"] == "orchestrator/free"
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
        probe_capability=lambda name, **kwargs: gateway_module().ProbeReceipt(
            name, 200
        ),
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
        list_models=lambda: gateway_module().ProbeReceipt("discovery", 200),
        probe_capability=lambda name, **kwargs: gateway_module().ProbeReceipt(
            name, 200
        ),
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


@pytest.mark.parametrize(
    "probe_name", ["discovery", "json_object", "json_schema", "tool_call"]
)
@pytest.mark.parametrize(
    "category_name",
    [
        "authentication_failed",
        "transport_failed",
        "invalid_response",
        "policy_unavailable",
        "capability_unavailable",
    ],
)
def test_typed_failure_preserves_stage_and_category(
    tmp_path, probe_name, category_name
):
    """Adapter failures retain only bounded stage/category/status evidence."""
    module = gateway_module()
    category = module.ProbeErrorCategory(category_name)

    def receipt(name):
        return (
            module.ProbeReceipt(name, None, category)
            if name == probe_name
            else module.ProbeReceipt(name, 200)
        )

    port = SimpleNamespace(
        list_models=lambda: receipt("discovery"),
        probe_capability=lambda name, **kwargs: receipt(name),
    )
    with pytest.raises(module.GatewayAdmissionError) as caught:
        module.verify_external_gateway(gateway_configuration(tmp_path), port)
    assert caught.value.evidence == {
        "probe_name": probe_name,
        "http_status": None,
        "result": "failed",
        "error_category": category_name,
    }


@pytest.mark.parametrize("bad_receipt", [True, {"error_category": "secret"}, "secret"])
def test_untyped_receipt_fails_without_raw_details(tmp_path, bad_receipt):
    """Legacy booleans and raw response mappings cannot satisfy admission."""
    module = gateway_module()
    port = SimpleNamespace(list_models=lambda: bad_receipt)
    with pytest.raises(module.GatewayAdmissionError) as caught:
        module.verify_external_gateway(gateway_configuration(tmp_path), port)
    assert caught.value.evidence["error_category"] == "invalid_response"
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("probe_name", "secret"),
        ("http_status", True),
        ("http_status", 600),
        ("http_status", "secret"),
        ("error_category", "secret"),
        ("http_status", None),
    ],
)
def test_malformed_receipt_fields_are_sanitized(tmp_path, field, value):
    """Dataclass construction alone is not trust-boundary validation."""
    module = gateway_module()
    values = {"probe_name": "discovery", "http_status": 200, "error_category": None}
    values[field] = value
    port = SimpleNamespace(list_models=lambda: module.ProbeReceipt(**values))
    with pytest.raises(module.GatewayAdmissionError) as caught:
        module.verify_external_gateway(gateway_configuration(tmp_path), port)
    assert caught.value.evidence == {
        "probe_name": "discovery",
        "http_status": None,
        "result": "failed",
        "error_category": "invalid_response",
    }


@pytest.mark.parametrize(
    "failure_kind",
    [
        "authentication_failed",
        "transport_failed",
        "invalid_response",
        "policy_unavailable",
        "capability_unavailable",
        "raw_exception",
        "malformed",
    ],
)
@pytest.mark.parametrize("failing_stage", ["discovery", "json_schema"])
def test_main_preserves_safe_failure_and_never_exports_readiness(
    tmp_path, monkeypatch, capsys, failure_kind, failing_stage
):
    """Main retains validated probe failure details without exception text."""
    module = gateway_module()
    config = gateway_configuration(tmp_path)

    def probe(name):
        if name != failing_stage:
            return module.ProbeReceipt(name, 200)
        if failure_kind == "raw_exception":
            raise RuntimeError("private-upstream-body-with-secret")
        if failure_kind == "malformed":
            return module.ProbeReceipt("secret", "secret", "secret")
        return module.ProbeReceipt(name, None, module.ProbeErrorCategory(failure_kind))

    monkeypatch.setattr(
        module,
        "RELEASED_GATEWAY_ADAPTERS",
        {
            "test": lambda config: SimpleNamespace(
                list_models=lambda: probe("discovery"),
                probe_capability=lambda name, **kwargs: probe(name),
            )
        },
    )
    for key, value in {
        "CONTEXTUAL_ORCHESTRATOR_GATEWAY_CONTRACT_REVISION": "test",
        "CONTEXTUAL_ORCHESTRATOR_BASE_URL": config.base_url,
        "CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE": str(config.token_file),
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_ENV": str(tmp_path / "github-env"),
    }.items():
        monkeypatch.setenv(key, value)
    assert module.main() == 1
    output = capsys.readouterr().out
    assert "secret" not in output
    assert f'"probe_name": "{failing_stage}"' in output
    expected_category = (
        "invalid_response"
        if failure_kind in {"raw_exception", "malformed"}
        else failure_kind
    )
    assert f'"error_category": "{expected_category}"' in output
    assert not (tmp_path / "github-env").exists()
    assert not list(tmp_path.glob("external-review-*"))


@pytest.mark.parametrize(
    "tampered_evidence",
    [
        {
            "probe_name": "discovery",
            "http_status": 401,
            "result": "secret",
            "error_category": "authentication_failed",
            "raw_body": "secret",
        },
        {"probe_name": "secret", "http_status": "secret", "error_category": "secret"},
        "secret",
        "missing",
        "inaccessible",
    ],
)
def test_main_projects_factory_admission_errors(
    tmp_path, monkeypatch, capsys, tampered_evidence
):
    """Mutable exception evidence cannot add raw fields at final serialization."""
    module = gateway_module()
    config = gateway_configuration(tmp_path)

    def factory(config):
        error = module.GatewayAdmissionError("authentication_failed")
        if tampered_evidence == "missing":
            del error.evidence
            error.args = ("secret",)
        elif tampered_evidence == "inaccessible":

            class InaccessibleAdmissionError(module.GatewayAdmissionError):
                def __getattribute__(self, field_name):
                    if field_name == "evidence":
                        raise RuntimeError("secret")
                    return super().__getattribute__(field_name)

            error = InaccessibleAdmissionError("authentication_failed")
            error.args = ("secret",)
        else:
            error.evidence = tampered_evidence
        raise error

    monkeypatch.setattr(module, "RELEASED_GATEWAY_ADAPTERS", {"test": factory})
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_GATEWAY_CONTRACT_REVISION", "test")
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_BASE_URL", config.base_url)
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE", str(config.token_file))
    output_file = tmp_path / "github-env"
    monkeypatch.setenv("GITHUB_ENV", str(output_file))
    assert module.main() == 1
    output = capsys.readouterr().out
    assert "secret" not in output
    evidence = json.loads(output.removeprefix("::error::"))
    assert set(evidence) == {"probe_name", "http_status", "result", "error_category"}
    assert evidence["result"] == "failed"
    assert not output_file.exists()
