"""Tests for Noema's shared free-first fallback adapter."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from scripts.ci import noema_review_gate as noema


def test_noema_exhausts_free_candidates_before_custom_paid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two NIM failures advance to the existing custom transport only afterward."""
    monkeypatch.setenv("TARGET_REPOSITORY_PRIVATE", "false")
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "nim-secret")
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://paid.example/chat")
    monkeypatch.setenv("NOEMA_LLM_MODEL", "paid-model")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "paid-secret")
    monkeypatch.setattr(
        noema,
        "plan_models",
        lambda *args, **kwargs: (
            "nvidia/nemotron-3-ultra-550b-a55b",
            "nvidia/llama-3.3-nemotron-super-49b-v1.5",
            "configured/noema-custom",
        ),
    )
    attempts: list[tuple[str, str, str]] = []

    def fake_call(*args, **kwargs):
        attempts.append(
            (
                os.environ["NOEMA_LLM_API_URL"],
                os.environ["NOEMA_LLM_MODEL"],
                os.environ["NOEMA_LLM_API_KEY"],
            )
        )
        if len(attempts) < 3:
            raise TimeoutError("provider timeout with secret")
        return {"decision": "approve", "summary": "ok", "findings": []}

    monkeypatch.setattr(noema, "_SINGLE_MODEL_CALL_LLM", fake_call)
    verdict = noema.call_llm("owner/repo", 1, {}, "diff", False, "context")
    assert verdict["decision"] == "approve"
    assert [attempt[1] for attempt in attempts] == [
        "nvidia/nemotron-3-ultra-550b-a55b",
        "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "paid-model",
    ]
    assert attempts[-1] == (
        "https://paid.example/chat",
        "paid-model",
        "paid-secret",
    )
    assert os.environ["NOEMA_LLM_API_URL"] == "https://paid.example/chat"
    assert os.environ["NOEMA_LLM_API_KEY"] == "paid-secret"


def test_noema_plan_receives_visibility_capability_and_synthetic_custom_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Policy eligibility sees only secret presence and the trusted target visibility."""
    monkeypatch.setenv("TARGET_REPOSITORY_PRIVATE", "true")
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://paid.example/chat")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "paid-secret")
    monkeypatch.delenv("NOEMA_LLM_MODEL", raising=False)
    seen = {}

    def fake_plan(agent, **kwargs):
        seen["agent"] = agent
        seen.update(kwargs)
        return ("configured/noema-custom",)

    monkeypatch.setattr(noema, "plan_models", fake_plan)
    monkeypatch.setattr(
        noema,
        "_SINGLE_MODEL_CALL_LLM",
        lambda *args, **kwargs: {"decision": "comment"},
    )
    assert noema.call_llm("owner/repo", 2, {}, "", False)["decision"] == "comment"
    assert seen["agent"] == "noema"
    assert seen["repository_visibility"] == "private"
    assert seen["required_capabilities"] == ("structured_output",)
    assert seen["environ"]["NOEMA_CUSTOM_LLM_CONFIGURED"] == "1"


def test_noema_auto_nim_default_is_not_duplicated_as_custom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Workflow-generated NIM settings do not become a duplicate paid fallback."""
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "same-key")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "same-key")
    monkeypatch.setenv("NOEMA_LLM_API_URL", noema._NVIDIA_API_URL)
    monkeypatch.setenv(
        "NOEMA_LLM_MODEL", "nvidia/nemotron-3-ultra-550b-a55b"
    )
    assert noema._custom_noema_config() is None


def test_noema_configuration_helpers_reject_invalid_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Visibility, model mapping, and absent keys fail closed."""
    monkeypatch.setenv("TARGET_REPOSITORY_PRIVATE", "maybe")
    with pytest.raises(RuntimeError, match="true or false"):
        noema._repository_visibility()
    monkeypatch.setenv("TARGET_REPOSITORY_PRIVATE", "")
    assert noema._repository_visibility() == "public"
    monkeypatch.setenv("TARGET_REPOSITORY_PRIVATE", "true")
    assert noema._repository_visibility() == "private"

    with pytest.raises(RuntimeError, match="without configuration"):
        noema._candidate_environment("configured/noema-custom", None)
    with pytest.raises(RuntimeError, match="unsupported model"):
        noema._candidate_environment("other/model", None)
    monkeypatch.delenv("NVIDIA_NIM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="unavailable"):
        noema._candidate_environment(
            "nvidia/nemotron-3-super-120b-a12b", None
        )


def test_noema_empty_configuration_translates_policy_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty eligible pool retains Noema's established not-configured failure."""
    for name in (
        "NOEMA_LLM_API_URL",
        "NOEMA_LLM_API_KEY",
        "NOEMA_LLM_MODEL",
        "NVIDIA_NIM_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        noema,
        "plan_models",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            noema.FallbackPolicyIntegrationError("none")
        ),
    )
    with pytest.raises(RuntimeError, match="no eligible configured model"):
        noema.call_llm("owner/repo", 1, {}, "", False)


def test_noema_nonempty_policy_integration_failure_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Supply-chain policy failures are not disguised as provider exhaustion."""
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "present")
    error = noema.FallbackPolicyIntegrationError("receipt mismatch")
    monkeypatch.setattr(
        noema,
        "plan_models",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
    )
    with pytest.raises(noema.FallbackPolicyIntegrationError) as caught:
        noema.call_llm("owner/repo", 1, {}, "", False)
    assert caught.value is error


def test_noema_single_failure_is_reraised_and_multiple_failures_are_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Compatibility keeps one error type; exhaustion reports no secret messages."""
    custom = {
        "NOEMA_LLM_API_URL": "https://paid.example/chat",
        "NOEMA_LLM_MODEL": "paid",
        "NOEMA_LLM_API_KEY": "top-secret",
    }
    monkeypatch.setenv("NOEMA_LLM_API_URL", custom["NOEMA_LLM_API_URL"])
    monkeypatch.setenv("NOEMA_LLM_MODEL", custom["NOEMA_LLM_MODEL"])
    monkeypatch.setenv("NOEMA_LLM_API_KEY", custom["NOEMA_LLM_API_KEY"])
    monkeypatch.setattr(
        noema, "plan_models", lambda *args, **kwargs: ("configured/noema-custom",)
    )
    failure = ValueError("top-secret invalid URL")
    monkeypatch.setattr(
        noema,
        "_SINGLE_MODEL_CALL_LLM",
        lambda *args, **kwargs: (_ for _ in ()).throw(failure),
    )
    with pytest.raises(ValueError) as caught:
        noema.call_llm("owner/repo", 1, {}, "", False)
    assert caught.value is failure

    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "nim-secret")
    monkeypatch.setattr(
        noema,
        "plan_models",
        lambda *args, **kwargs: (
            "nvidia/nemotron-3-ultra-550b-a55b",
            "configured/noema-custom",
        ),
    )
    monkeypatch.setattr(
        noema,
        "_SINGLE_MODEL_CALL_LLM",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            TimeoutError("top-secret timeout")
        ),
    )
    with pytest.raises(RuntimeError, match="exhausted") as exhausted:
        noema.call_llm("owner/repo", 1, {}, "", False)
    combined = str(exhausted.value) + capsys.readouterr().err
    assert "top-secret" not in combined
    assert "TimeoutError" in combined


def test_noema_environment_context_restores_absent_and_present_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Candidate transport settings cannot leak into the next workflow phase."""
    monkeypatch.setenv("NOEMA_LLM_MODEL", "original")
    monkeypatch.delenv("NOEMA_LLM_API_KEY", raising=False)
    with noema._temporary_noema_environment(
        {
            "NOEMA_LLM_MODEL": "temporary",
            "NOEMA_LLM_API_KEY": "temporary-key",
        }
    ):
        assert os.environ["NOEMA_LLM_MODEL"] == "temporary"
        assert os.environ["NOEMA_LLM_API_KEY"] == "temporary-key"
    assert os.environ["NOEMA_LLM_MODEL"] == "original"
    assert "NOEMA_LLM_API_KEY" not in os.environ


def test_noema_failure_label_includes_only_http_status() -> None:
    """Failure labels include no provider body or credential value."""
    assert noema._failure_label(ValueError("secret")) == "ValueError"
    assert noema._failure_label(SimpleNamespace(code=429)) == "SimpleNamespace:429"  # type: ignore[arg-type]


def test_noema_wrapper_rejects_missing_core(tmp_path) -> None:
    """The adapter never silently replaces a missing trusted Noema core."""
    import importlib.util
    from pathlib import Path

    source = Path(noema._WRAPPER_FILE)
    core = Path(noema._CORE_PATH)
    parked = tmp_path / core.name
    core.rename(parked)
    try:
        spec = importlib.util.spec_from_file_location("isolated_noema", source)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        with pytest.raises(RuntimeError, match="core is unavailable"):
            spec.loader.exec_module(module)
    finally:
        parked.rename(core)
