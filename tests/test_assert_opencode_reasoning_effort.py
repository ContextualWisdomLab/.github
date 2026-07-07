import json
import runpy
import sys

import pytest

from scripts.ci import assert_opencode_reasoning_effort as guard


def write_config(tmp_path, models):
    """Write a minimal OpenCode config and return its path."""
    path = tmp_path / "opencode.jsonc"
    path.write_text(
        json.dumps({"provider": {"github-models": {"models": models}}}),
        encoding="utf-8",
    )
    return path


def high_reasoning_model():
    """Return a reasoning-capable model config with high effort enabled."""
    return {
        "reasoning": True,
        "options": {"reasoningEffort": "high"},
        "variants": {"high": {"reasoningEffort": "high"}},
    }


def test_known_reasoning_capable_model_families():
    """Known reasoning-capable families are recognized."""
    assert guard.is_known_reasoning_capable("openai/gpt-5")
    assert guard.is_known_reasoning_capable("openai/o3-mini")
    assert guard.is_known_reasoning_capable("openai/o4-mini")
    assert guard.is_known_reasoning_capable("deepseek/deepseek-r1-0528")
    assert not guard.is_known_reasoning_capable("deepseek/deepseek-v3-0324")


def test_validate_candidate_accepts_high_effort_and_non_reasoning_models(tmp_path):
    """High-effort reasoning models pass while non-reasoning models are ignored."""
    config_path = write_config(
        tmp_path,
        {
            "openai/o3": high_reasoning_model(),
            "deepseek/deepseek-v3-0324": {"tool_call": True},
        },
    )
    config = guard.load_config(config_path)

    assert guard.validate_candidate(config, "github-models/openai/o3") == []
    assert (
        guard.validate_candidate(config, "github-models/deepseek/deepseek-v3-0324")
        == []
    )


def test_validate_candidate_reports_missing_and_unqualified_models():
    """Unknown and unqualified candidates fail with actionable messages."""
    config = {"provider": {"github-models": {"models": {}}}}

    assert guard.validate_candidate(config, "openai-o3") == [
        "OpenCode candidate openai-o3 is not provider-qualified."
    ]
    assert guard.validate_candidate(config, "github-models/openai/o3") == [
        "OpenCode candidate github-models/openai/o3 is not defined in opencode.jsonc "
        "under provider github-models."
    ]


def test_validate_candidate_skips_unknown_non_reasoning_provider_fallbacks():
    """Unknown provider fallbacks pass when no reasoning-effort support is known."""
    config = {"provider": {"github-models": {"models": {}}}}

    assert guard.validate_candidate(config, "vertex_ai/fallback-one") == []


def test_validate_candidate_reports_each_missing_high_effort_field():
    """Reasoning-capable models must opt into high effort in every required field."""
    config = {
        "provider": {
            "github-models": {
                "models": {
                    "openai/o3": {
                        "reasoning": True,
                        "options": {"reasoningEffort": "low"},
                        "variants": {"high": {"reasoningEffort": "medium"}},
                    },
                    "deepseek/deepseek-r1-0528": {"tool_call": True},
                }
            }
        }
    }

    assert guard.validate_candidate(config, "github-models/openai/o3") == [
        "OpenCode reasoning-capable candidate github-models/openai/o3 must set "
        "options.reasoningEffort=high in opencode.jsonc.",
        "OpenCode reasoning-capable candidate github-models/openai/o3 must set "
        "variants.high.reasoningEffort=high in opencode.jsonc.",
    ]
    assert guard.validate_candidate(config, "github-models/deepseek/deepseek-r1-0528") == [
        "OpenCode reasoning-capable candidate github-models/deepseek/deepseek-r1-0528 "
        "must set reasoning=true in opencode.jsonc.",
        "OpenCode reasoning-capable candidate github-models/deepseek/deepseek-r1-0528 "
        "must set options.reasoningEffort=high in opencode.jsonc.",
        "OpenCode reasoning-capable candidate github-models/deepseek/deepseek-r1-0528 "
        "must set variants.high.reasoningEffort=high in opencode.jsonc.",
    ]


def test_load_config_reports_missing_and_invalid_json(tmp_path):
    """Config-loading errors are explicit."""
    with pytest.raises(SystemExit, match="OpenCode config not found"):
        guard.load_config(tmp_path / "missing.json")

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(SystemExit, match="OpenCode config is not valid JSON"):
        guard.load_config(invalid)


def test_main_reports_all_candidate_errors(tmp_path, capsys):
    """The CLI validates every candidate before returning failure."""
    config_path = write_config(
        tmp_path,
        {
            "openai/o3": {
                "reasoning": True,
                "options": {"reasoningEffort": "low"},
                "variants": {"high": {"reasoningEffort": "high"}},
            },
            "mistral-ai/mistral-medium-2505": {"tool_call": True},
        },
    )

    assert (
        guard.main(
            [
                "--config",
                str(config_path),
                "github-models/openai/o3",
                "github-models/mistral-ai/mistral-medium-2505",
            ]
        )
        == 1
    )
    assert "options.reasoningEffort=high" in capsys.readouterr().err


def test_module_entrypoint_success(monkeypatch, tmp_path):
    """The script entrypoint exits successfully for compliant candidates."""
    config_path = write_config(tmp_path, {"openai/gpt-5": high_reasoning_model()})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "assert_opencode_reasoning_effort.py",
            "--config",
            str(config_path),
            "github-models/openai/gpt-5",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("scripts.ci.assert_opencode_reasoning_effort", run_name="__main__")

    assert exc_info.value.code == 0
