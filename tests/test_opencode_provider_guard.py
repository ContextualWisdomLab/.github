"""Credential-isolation tests for one OpenCode model candidate process."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts" / "ci" / "opencode_provider_guard.sh"
ALL_CREDENTIALS = {
    "GH_TOKEN": "gh-secret",
    "GITHUB_TOKEN": "github-secret",
    "OPENCODE_APP_TOKEN": "app-secret",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "oidc-secret",
    "ACTIONS_ID_TOKEN_REQUEST_URL": "https://oidc.invalid",
    "ACTIONS_RUNTIME_TOKEN": "runtime-secret",
    "ACTIONS_CACHE_URL": "https://cache.invalid",
    "ACTIONS_RESULTS_URL": "https://results.invalid",
    "ACTIONS_RUNTIME_URL": "https://runtime.invalid",
    "STRIX_GITHUB_MODELS_TOKEN": "models-secret",
    "OPENCODE_API_KEY": "zen-secret",
    "OPENAI_API_KEY": "openai-secret",
    "OPENROUTER_API_KEY": "openrouter-secret",
    "NVIDIA_API_KEY": "nvidia-normalized-secret",
    "NVIDIA_NIM_API_KEY": "nvidia-source-secret",
}
COMMON_SENSITIVE_NAMES = {
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "OPENCODE_APP_TOKEN",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
    "ACTIONS_ID_TOKEN_REQUEST_URL",
    "ACTIONS_RUNTIME_TOKEN",
    "ACTIONS_CACHE_URL",
    "ACTIONS_RESULTS_URL",
    "ACTIONS_RUNTIME_URL",
}
PROVIDER_NAMES = {
    "STRIX_GITHUB_MODELS_TOKEN",
    "OPENCODE_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "NVIDIA_API_KEY",
    "NVIDIA_NIM_API_KEY",
}


@pytest.fixture
def fake_opencode(tmp_path: Path) -> Path:
    """Create a fake OpenCode executable that prints selected environment keys."""
    script = tmp_path / "fake-opencode.py"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"names = {sorted(ALL_CREDENTIALS)!r}\n"
        "print(json.dumps({name: os.environ.get(name) for name in names}))\n"
        "print(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def run_guard(real_bin: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run the real guard with an explicit child executable and credentials."""
    env = os.environ.copy()
    env.update(ALL_CREDENTIALS)
    env["OPENCODE_REAL_BIN"] = real_bin
    return subprocess.run(
        ["bash", str(GUARD), *arguments],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def invoke(fake_opencode: Path, *arguments: str) -> tuple[dict[str, str | None], list[str]]:
    """Run the real guard and parse the fake executable's observations."""
    result = run_guard(str(fake_opencode), *arguments)
    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    return json.loads(lines[0]), json.loads(lines[1])


def assert_absent(observed: dict[str, str | None], names: set[str]) -> None:
    """Assert every named credential was removed from the child environment."""
    assert {name for name in names if observed[name] is not None} == set()


def test_anonymous_free_model_receives_no_github_oidc_or_provider_credentials(
    fake_opencode: Path,
) -> None:
    """Anonymous free candidates never inherit unrelated automation secrets."""
    observed, argv = invoke(
        fake_opencode,
        "run",
        "review prompt",
        "--model",
        "opencode-free/nemotron-3-ultra-free",
    )

    assert_absent(observed, COMMON_SENSITIVE_NAMES | PROVIDER_NAMES)
    assert argv[-2:] == ["--model", "opencode-free/nemotron-3-ultra-free"]


@pytest.mark.parametrize(
    ("candidate", "kept"),
    [
        ("nvidia-nim/nvidia/nemotron-3-super-120b-a12b", {"NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY"}),
        ("opencode/gpt-5.6-terra", {"OPENCODE_API_KEY"}),
        ("openai/gpt-5.4", {"OPENAI_API_KEY"}),
        ("openrouter/openai/gpt-5.4", {"OPENROUTER_API_KEY"}),
        ("github-models/openai/gpt-5", {"STRIX_GITHUB_MODELS_TOKEN"}),
    ],
)
def test_paid_or_scoped_candidate_receives_only_its_provider_credentials(
    fake_opencode: Path,
    candidate: str,
    kept: set[str],
) -> None:
    """Each keyed provider is isolated from every other provider credential."""
    observed, _ = invoke(fake_opencode, "run", "prompt", "--model", candidate)

    assert_absent(observed, COMMON_SENSITIVE_NAMES | (PROVIDER_NAMES - kept))
    assert {name for name in kept if observed[name] is not None} == kept


@pytest.mark.parametrize(
    "arguments",
    [
        ("run", "prompt", "-m", "openai/gpt-5.4"),
        ("run", "prompt", "-m=openai/gpt-5.4"),
    ],
)
def test_short_model_alias_keeps_only_selected_provider_credentials(
    fake_opencode: Path,
    arguments: tuple[str, ...],
) -> None:
    """OpenCode's ``-m`` aliases receive the same scoped provider credential."""
    observed, _ = invoke(fake_opencode, *arguments)

    assert_absent(observed, COMMON_SENSITIVE_NAMES | (PROVIDER_NAMES - {"OPENAI_API_KEY"}))
    assert observed["OPENAI_API_KEY"] == "openai-secret"


def test_equals_form_model_argument_keeps_only_selected_provider_credentials(
    fake_opencode: Path,
) -> None:
    """The supported ``--model=value`` form receives the same scoped credential."""
    observed, argv = invoke(fake_opencode, "run", "prompt", "--model=openai/gpt-5.4")

    assert_absent(observed, COMMON_SENSITIVE_NAMES | (PROVIDER_NAMES - {"OPENAI_API_KEY"}))
    assert observed["OPENAI_API_KEY"] == "openai-secret"
    assert argv[-1] == "--model=openai/gpt-5.4"


def test_option_terminator_stops_model_selector_parsing(fake_opencode: Path) -> None:
    """Arguments after ``--`` cannot re-enable provider credentials in the guard."""
    observed, argv = invoke(
        fake_opencode,
        "run",
        "prompt",
        "--",
        "--model",
        "openai/gpt-5.4",
    )

    assert_absent(observed, COMMON_SENSITIVE_NAMES | PROVIDER_NAMES)
    assert argv[-3:] == ["--", "--model", "openai/gpt-5.4"]


def test_duplicate_model_arguments_fail_closed_before_model_execution(
    fake_opencode: Path,
) -> None:
    """Ambiguous duplicate model selectors are rejected before secrets reach a child."""
    result = run_guard(
        str(fake_opencode),
        "run",
        "prompt",
        "--model",
        "openai/gpt-5.4",
        "-m=opencode/gpt-5.6-terra",
    )

    assert result.returncode == 64
    assert result.stdout == ""
    assert "exactly one" in result.stderr


@pytest.mark.parametrize(
    ("arguments", "error_fragment"),
    [
        (("run", "prompt", "--model", "-m=openai/gpt-5.4"), "exactly one"),
        (("run", "prompt", "--model", "--"), "requires a model candidate"),
        (("run", "prompt", "--model", "--model=openai/gpt-5.4"), "exactly one"),
    ],
)
def test_selector_like_model_values_fail_closed_before_child_execution(
    fake_opencode: Path,
    arguments: tuple[str, ...],
    error_fragment: str,
) -> None:
    """A pending model selector may not consume another selector or ``--`` as its value."""
    result = run_guard(str(fake_opencode), *arguments)

    assert result.returncode == 64
    assert result.stdout == ""
    assert error_fragment in result.stderr


@pytest.mark.parametrize(
    ("real_bin", "arguments", "expected_code", "error_fragment"),
    [
        ("FAKE", (), 64, "Usage:"),
        ("", ("run", "prompt", "--model", "openai/gpt-5.4"), 69, "OPENCODE_REAL_BIN"),
        ("/definitely/not/executable", ("run", "prompt", "--model", "openai/gpt-5.4"), 69, "OPENCODE_REAL_BIN"),
        ("FAKE", ("run", "prompt", "--model"), 64, "requires a model candidate"),
        ("FAKE", ("run", "prompt", "-m"), 64, "requires a model candidate"),
    ],
)
def test_guard_argument_and_executable_failures_stop_before_child_execution(
    fake_opencode: Path,
    real_bin: str,
    arguments: tuple[str, ...],
    expected_code: int,
    error_fragment: str,
) -> None:
    """Malformed invocation boundaries fail closed before any credential-bearing child."""
    resolved_bin = str(fake_opencode) if real_bin == "FAKE" else real_bin
    result = run_guard(resolved_bin, *arguments)

    assert result.returncode == expected_code
    assert result.stdout == ""
    assert error_fragment in result.stderr


def test_export_receives_no_provider_credentials(fake_opencode: Path) -> None:
    """Session export is local and does not inherit any provider credential."""
    observed, argv = invoke(fake_opencode, "export", "session_123")

    assert_absent(observed, COMMON_SENSITIVE_NAMES | PROVIDER_NAMES)
    assert argv == ["export", "session_123"]


def test_unknown_model_prefix_fails_safe_without_provider_credentials(
    fake_opencode: Path,
) -> None:
    """New providers default to zero credentials until explicitly classified."""
    observed, _ = invoke(fake_opencode, "run", "prompt", "--model", "unknown/model")

    assert_absent(observed, COMMON_SENSITIVE_NAMES | PROVIDER_NAMES)
