"""Fail-closed optional Contextual Orchestrator provider attachment."""

from __future__ import annotations

import json
from pathlib import Path
import runpy
import sys

import pytest

from scripts.ci import attach_contextual_orchestrator_provider as attach


def nim_only_config() -> dict[str, object]:
    """Return the current NIM-direct isolated catalog shape."""
    return {
        "model": "nvidia-nim/nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "small_model": "nvidia-nim/meta/llama-3.3-70b-instruct",
        "enabled_providers": ["nvidia-nim"],
        "provider": {
            "nvidia-nim": {
                "options": {
                    "baseURL": "https://integrate.api.nvidia.com/v1",
                    "apiKey": "{env:NVIDIA_API_KEY}",
                }
            }
        },
    }


def write_config(tmp_path: Path, payload: dict[str, object]) -> Path:
    """Write one isolated OpenCode config for helper tests."""
    path = tmp_path / "opencode.jsonc"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_unset_url_is_a_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing orchestrator URL leaves the NIM-direct catalog unchanged."""
    path = write_config(tmp_path, nim_only_config())
    monkeypatch.delenv("CONTEXTUAL_ORCHESTRATOR_URL", raising=False)

    assert attach.main([str(path)]) == 0
    assert json.loads(path.read_text(encoding="utf-8")) == nim_only_config()


def test_blank_url_is_a_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Whitespace-only orchestrator URL does not attach a provider."""
    path = write_config(tmp_path, nim_only_config())
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_URL", "  \n")

    assert attach.main([str(path)]) == 0
    assert json.loads(path.read_text(encoding="utf-8")) == nim_only_config()


def test_https_url_attaches_provider_without_changing_nim_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A valid https URL adds one provider and keeps NIM as the default model."""
    path = write_config(tmp_path, nim_only_config())
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_URL", "https://orchestrator.example/v1/")

    assert attach.main([str(path)]) == 0
    config = json.loads(path.read_text(encoding="utf-8"))
    assert config["model"] == "nvidia-nim/nvidia/llama-3.3-nemotron-super-49b-v1.5"
    assert config["small_model"] == "nvidia-nim/meta/llama-3.3-70b-instruct"
    assert config["enabled_providers"] == ["nvidia-nim", "contextual-orchestrator"]
    assert config["provider"]["contextual-orchestrator"] == {
        "npm": "@ai-sdk/openai-compatible",
        "name": "Contextual Orchestrator",
        "options": {"baseURL": "https://orchestrator.example/v1"},
    }
    assert "github-models" not in config["provider"]
    assert "Attached contextual-orchestrator provider" in capsys.readouterr().out


def test_loopback_http_sidecar_is_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The future review-job sidecar may listen on loopback http."""
    path = write_config(tmp_path, nim_only_config())
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_URL", "http://127.0.0.1:4000/v1")

    assert attach.main([str(path)]) == 0
    config = json.loads(path.read_text(encoding="utf-8"))
    assert config["provider"]["contextual-orchestrator"]["options"]["baseURL"] == (
        "http://127.0.0.1:4000/v1"
    )


def test_localhost_http_sidecar_is_allowed() -> None:
    """localhost is treated as the same loopback sidecar class as 127.0.0.1."""
    assert (
        attach.normalize_orchestrator_url("http://localhost:4000/v1")
        == "http://localhost:4000/v1"
    )
    assert (
        attach.normalize_orchestrator_url("http://[::1]:4000/v1")
        == "http://[::1]:4000/v1"
    )


def test_existing_orchestrator_enabled_entry_is_not_duplicated() -> None:
    """Re-attaching does not append a second enabled_providers entry."""
    config = nim_only_config()
    config["enabled_providers"] = ["nvidia-nim", "contextual-orchestrator"]

    updated = attach.attach_orchestrator_provider(
        config, "https://orchestrator.example/v1"
    )

    assert updated["enabled_providers"] == ["nvidia-nim", "contextual-orchestrator"]


def test_github_models_url_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """GitHub Models endpoints are never a valid orchestrator URL."""
    original = nim_only_config()
    path = write_config(tmp_path, original)
    monkeypatch.setenv(
        "CONTEXTUAL_ORCHESTRATOR_URL",
        "https://models.github.ai/inference",
    )

    assert attach.main([str(path)]) == 1
    assert "must not point at GitHub Models" in capsys.readouterr().err
    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_non_loopback_http_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plain http is only for a local sidecar, not a remote fallback."""
    path = write_config(tmp_path, nim_only_config())
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_URL", "http://orchestrator.example/v1")

    assert attach.main([str(path)]) == 1


def test_embedded_credentials_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Userinfo in the orchestrator URL is not accepted."""
    path = write_config(tmp_path, nim_only_config())
    monkeypatch.setenv(
        "CONTEXTUAL_ORCHESTRATOR_URL",
        "https://user:token@orchestrator.example/v1",
    )

    assert attach.main([str(path)]) == 1


def test_missing_scheme_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A host without an http(s) scheme is not a usable OpenAI-compatible base."""
    path = write_config(tmp_path, nim_only_config())
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_URL", "orchestrator.example/v1")

    assert attach.main([str(path)]) == 1


def test_missing_host_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """https without a host is not a usable sidecar URL."""
    path = write_config(tmp_path, nim_only_config())
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_URL", "https://")

    assert attach.main([str(path)]) == 1


def test_missing_config_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A set URL cannot attach into a missing isolated catalog."""
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_URL", "https://orchestrator.example/v1")

    assert attach.main([str(tmp_path / "missing.jsonc")]) == 1


def test_invalid_json_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Corrupt isolated catalogs are not rewritten."""
    path = tmp_path / "opencode.jsonc"
    path.write_text("{", encoding="utf-8")
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_URL", "https://orchestrator.example/v1")

    assert attach.main([str(path)]) == 1


def test_non_object_root_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A JSON array is not an OpenCode config."""
    path = tmp_path / "opencode.jsonc"
    path.write_text("[]", encoding="utf-8")
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_URL", "https://orchestrator.example/v1")

    assert attach.main([str(path)]) == 1


def test_github_models_provider_map_fails_closed() -> None:
    """Do not attach beside a leftover GitHub Models provider."""
    config = nim_only_config()
    providers = config["provider"]
    assert isinstance(providers, dict)
    providers["github-models"] = {}

    with pytest.raises(SystemExit, match="github-models"):
        attach.attach_orchestrator_provider(config, "https://orchestrator.example/v1")


def test_missing_nvidia_nim_enabled_provider_fails_closed() -> None:
    """The optional path cannot replace NIM-direct as the enabled default."""
    config = nim_only_config()
    config["enabled_providers"] = ["openai"]

    with pytest.raises(SystemExit, match="nvidia-nim"):
        attach.attach_orchestrator_provider(config, "https://orchestrator.example/v1")


def test_non_object_provider_map_fails_closed() -> None:
    """A broken provider map is not rewritten."""
    config = nim_only_config()
    config["provider"] = []

    with pytest.raises(SystemExit, match="provider map"):
        attach.attach_orchestrator_provider(config, "https://orchestrator.example/v1")


def test_module_entrypoint_skips_when_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The script entrypoint exits successfully when the sidecar URL is absent."""
    path = write_config(tmp_path, nim_only_config())
    monkeypatch.delenv("CONTEXTUAL_ORCHESTRATOR_URL", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["attach_contextual_orchestrator_provider.py", str(path)],
    )

    module = sys.modules.pop(
        "scripts.ci.attach_contextual_orchestrator_provider", None
    )
    with pytest.raises(SystemExit) as exc_info:
        try:
            runpy.run_module(
                "scripts.ci.attach_contextual_orchestrator_provider",
                run_name="__main__",
            )
        finally:
            if module is not None:
                sys.modules["scripts.ci.attach_contextual_orchestrator_provider"] = (
                    module
                )

    assert exc_info.value.code == 0
