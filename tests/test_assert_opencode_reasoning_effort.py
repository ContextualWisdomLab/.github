import json
import runpy
import sys
<<<<<<< HEAD
import time
=======
>>>>>>> 38a1692b (merge: integrate latest review authority into CodeQL owner)

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


def test_strip_jsonc_comments_removes_line_and_block_comments():
    """Line and block comments outside strings are dropped, newlines preserved."""
    text = (
        '{\n'
        '  // leading note\n'
        '  "a": 1, /* inline block\n'
        '  spanning lines */ "b": 2\n'
        '}\n'
    )

    stripped = guard.strip_jsonc_comments(text)

    assert json.loads(stripped) == {"a": 1, "b": 2}
    assert stripped.count("\n") == text.count("\n")


<<<<<<< HEAD
def test_strip_jsonc_comments_preserves_block_comment_line_endings():
    """Block-comment removal preserves every LF and CR character in order."""
    text = '{\r\n  "a": 1, /* first\r\nsecond\rthird\nfourth */ "b": 2\r\n}\r\n'

    stripped = guard.strip_jsonc_comments(text)

    assert json.loads(stripped) == {"a": 1, "b": 2}
    assert [character for character in stripped if character in "\r\n"] == [
        character for character in text if character in "\r\n"
    ]


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1, /* unterminated block comment',
        '{"a": "unterminated // string',
    ],
)
def test_load_config_rejects_unterminated_jsonc_constructs(tmp_path, text):
    """Malformed comments and strings remain invalid instead of being accepted."""
    config_path = tmp_path / "opencode.jsonc"
    config_path.write_text(text, encoding="utf-8")

    with pytest.raises(SystemExit, match="OpenCode config is not valid JSON"):
        guard.load_config(config_path)


def test_strip_jsonc_comments_has_bounded_large_comment_runtime():
    """A one-megabyte adversarial block comment is stripped within two seconds."""
    comment_body = "x\\/" * 349_526
    text = '{"a": 1, /*' + comment_body + '\r\n*/ "b": 2}'

    started_at = time.perf_counter()
    stripped = guard.strip_jsonc_comments(text)
    elapsed_seconds = time.perf_counter() - started_at

    assert json.loads(stripped) == {"a": 1, "b": 2}
    assert "\r\n" in stripped
    assert elapsed_seconds < 2.0


=======
>>>>>>> 38a1692b (merge: integrate latest review authority into CodeQL owner)
def test_strip_jsonc_comments_preserves_double_slash_inside_strings():
    """A string value containing // (a URL) is not treated as a comment."""
    text = '{\n  "$schema": "https://opencode.ai/config.json" // trailing note\n}\n'

    stripped = guard.strip_jsonc_comments(text)

    assert json.loads(stripped) == {"$schema": "https://opencode.ai/config.json"}


def test_strip_jsonc_comments_respects_escaped_quotes_in_strings():
    """An escaped quote inside a string does not end string tracking early."""
    text = '{"a": "quote \\" then // not a comment", "b": 1}'

    stripped = guard.strip_jsonc_comments(text)

    assert json.loads(stripped) == {"a": 'quote " then // not a comment', "b": 1}


def test_load_config_tolerates_real_opencode_jsonc_comment_style(tmp_path):
    """The exact comment style used in the repository's opencode.jsonc loads."""
    config_path = tmp_path / "opencode.jsonc"
    config_path.write_text(
        '{\n'
        '  "$schema": "https://opencode.ai/config.json",\n'
        '  // NOT switched to "contextual-orchestrator/contextual-orchestrator" yet:\n'
        '  // that requires provisioning first.\n'
        '  "model": "nvidia-nim/nvidia/llama-3.3-nemotron-super-49b-v1.5"\n'
        '}\n',
        encoding="utf-8",
    )

    config = guard.load_config(config_path)

    assert config["model"] == "nvidia-nim/nvidia/llama-3.3-nemotron-super-49b-v1.5"


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

    module = sys.modules.pop("scripts.ci.assert_opencode_reasoning_effort", None)
    with pytest.raises(SystemExit) as exc_info:
        try:
            runpy.run_module("scripts.ci.assert_opencode_reasoning_effort", run_name="__main__")
        finally:
            if module is not None:
                sys.modules["scripts.ci.assert_opencode_reasoning_effort"] = module

    assert exc_info.value.code == 0
def test_strip_jsonc_comments_prevents_token_fusion() -> None:
    """Test that comments replaced with empty strings do not fuse adjacent tokens."""
    # Ensure numeric tokens do not fuse
    assert guard.strip_jsonc_comments('{"a":1/*x*/2}') == '{"a":1 2}'
    assert guard.strip_jsonc_comments('{"a":-/*x*/1}') == '{"a":- 1}'
    assert guard.strip_jsonc_comments('[1/*x*/.5]') == '[1 .5]'

    # Check that whitespace is retained if it exists
    assert guard.strip_jsonc_comments('{"a":1/* x */2}') == '{"a":1 x 2}'
