"""Behavioral tests for shared fallback shell adapters."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
OPENCODE_ADAPTER = ROOT / "scripts" / "ci" / "run_opencode_review_model_pool.sh"
STRIX_UTILS = ROOT / "scripts" / "ci" / "strix_model_utils.sh"


def bash() -> str:
    """Return a Bash executable for adapter tests."""
    executable = shutil.which("bash")
    if executable is None:
        pytest.skip("bash is required")
    return executable


def write_fake_policy(path: Path) -> None:
    """Write a policy CLI fixture that records arguments and prints a plan."""
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "capture = os.environ.get('FAKE_POLICY_CAPTURE')\n"
        "if capture:\n"
        "    pathlib.Path(capture).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
        "if os.environ.get('FAKE_POLICY_FAIL') == '1':\n"
        "    raise SystemExit(2)\n"
        "plan = os.environ.get('FAKE_POLICY_PLAN', '')\n"
        "if plan:\n"
        "    print(plan.replace(' ', '\\n'))\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def prepare_opencode_adapter(tmp_path: Path) -> tuple[Path, Path]:
    """Copy the OpenCode adapter beside fake policy and core executables."""
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    adapter = script_dir / OPENCODE_ADAPTER.name
    adapter.write_bytes(OPENCODE_ADAPTER.read_bytes())
    adapter.chmod(0o755)
    policy = script_dir / "contextual_fallback_policy.py"
    write_fake_policy(policy)
    core = script_dir / "run_opencode_review_model_pool_core.sh"
    core.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"${OPENCODE_MODEL_CANDIDATES-}\"\n"
        "printf 'args=%s\\n' \"$*\"\n",
        encoding="utf-8",
    )
    core.chmod(0o755)
    return adapter, core


def test_opencode_adapter_applies_policy_order_and_preserves_arguments(
    tmp_path: Path,
) -> None:
    """The adapter replaces only the pool order before invoking the core."""
    adapter, _ = prepare_opencode_adapter(tmp_path)
    capture = tmp_path / "capture.json"
    env = os.environ.copy()
    env.update(
        {
            "OPENCODE_MODEL_CANDIDATES": "paid/model free/model",
            "OPENCODE_REPOSITORY_VISIBILITY": "private",
            "FAKE_POLICY_PLAN": "free/model paid/model",
            "FAKE_POLICY_CAPTURE": str(capture),
        }
    )
    result = subprocess.run(
        [bash(), str(adapter), "one", "two"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["free/model paid/model", "args=one two"]
    args = json.loads(capture.read_text(encoding="utf-8"))
    assert args[:4] == [
        "--agent",
        "opencode-review",
        "--repository-visibility",
        "private",
    ]
    assert "OPENCODE_MODEL_CANDIDATES" in args
    assert "code_review" in args


def test_opencode_adapter_infers_public_and_delegates_empty_pool(
    tmp_path: Path,
) -> None:
    """Public free candidates are detected; the core keeps its no-model path."""
    adapter, _ = prepare_opencode_adapter(tmp_path)
    capture = tmp_path / "capture.json"
    env = os.environ.copy()
    env.update(
        {
            "OPENCODE_MODEL_CANDIDATES": "opencode-free/free paid/model",
            "FAKE_POLICY_PLAN": "opencode-free/free paid/model",
            "FAKE_POLICY_CAPTURE": str(capture),
        }
    )
    result = subprocess.run(
        [bash(), str(adapter)], env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    args = json.loads(capture.read_text(encoding="utf-8"))
    assert args[args.index("--repository-visibility") + 1] == "public"

    env["OPENCODE_MODEL_CANDIDATES"] = ""
    capture.unlink()
    result = subprocess.run(
        [bash(), str(adapter)], env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    assert result.stdout.splitlines()[0] == ""
    assert not capture.exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("bad_visibility", "must be public"),
        ("policy_failure", "could not be created"),
        ("empty_plan", "plan is empty"),
    ],
)
def test_opencode_adapter_fails_closed(
    tmp_path: Path, mutation: str, message: str
) -> None:
    """Invalid policy inputs cannot fall through to an ungoverned core run."""
    adapter, _ = prepare_opencode_adapter(tmp_path)
    env = os.environ.copy()
    env["OPENCODE_MODEL_CANDIDATES"] = "paid/model"
    if mutation == "bad_visibility":
        env["OPENCODE_REPOSITORY_VISIBILITY"] = "secret"
    elif mutation == "policy_failure":
        env["FAKE_POLICY_FAIL"] = "1"
    else:
        env["FAKE_POLICY_PLAN"] = ""
    result = subprocess.run(
        [bash(), str(adapter)], env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 2
    assert message in result.stderr


def test_opencode_adapter_rejects_missing_or_symlink_dependencies(
    tmp_path: Path,
) -> None:
    """Trusted adapter dependencies must be ordinary repository files."""
    adapter, core = prepare_opencode_adapter(tmp_path)
    policy = adapter.with_name("contextual_fallback_policy.py")
    policy.unlink()
    env = os.environ.copy()
    env["OPENCODE_MODEL_CANDIDATES"] = "paid/model"
    result = subprocess.run(
        [bash(), str(adapter)], env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 2
    assert "policy adapter" in result.stderr
    write_fake_policy(policy)
    core.unlink()
    core.symlink_to(policy)
    result = subprocess.run(
        [bash(), str(adapter)], env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 2
    assert "core is unavailable" in result.stderr


def prepare_strix_fixture(tmp_path: Path) -> dict[str, Path]:
    """Create trusted input files and a fake policy beside model utilities."""
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    utils = script_dir / STRIX_UTILS.name
    utils.write_bytes(STRIX_UTILS.read_bytes())
    policy = script_dir / "contextual_fallback_policy.py"
    write_fake_policy(policy)
    input_root = tmp_path / "inputs"
    input_root.mkdir()
    primary = input_root / "primary.txt"
    primary_key = input_root / "primary.key"
    github_key = input_root / "github.key"
    primary_key.write_text("primary-secret", encoding="utf-8")
    github_key.write_text("github-secret", encoding="utf-8")
    api_base = input_root / "base.txt"
    return {
        "utils": utils,
        "input_root": input_root,
        "primary": primary,
        "primary_key": primary_key,
        "github_key": github_key,
        "api_base": api_base,
    }


def run_strix_source(
    fixture: dict[str, Path], *, plan: str, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Source model utilities and print the policy-mutated model contract."""
    capture = fixture["input_root"] / "capture.json"
    env = os.environ.copy()
    env.update(
        {
            "SCRIPT_DIR": str(fixture["utils"].parent),
            "STRIX_LLM_FILE": str(fixture["primary"]),
            "STRIX_INPUT_FILE_ROOT": str(fixture["input_root"]),
            "RUNNER_TEMP": str(fixture["input_root"]),
            "LLM_API_KEY_FILE": str(fixture["primary_key"]),
            "STRIX_GITHUB_MODELS_KEY_FILE": str(fixture["github_key"]),
            "FAKE_POLICY_PLAN": plan,
            "FAKE_POLICY_CAPTURE": str(capture),
        }
    )
    if extra_env:
        env.update(extra_env)
    command = (
        'set -euo pipefail; '
        f'source "{fixture["utils"]}"; '
        'printf "primary=%s\\n" "$(cat "$STRIX_LLM_FILE")"; '
        'printf "fallback=%s\\n" "$STRIX_FALLBACK_MODELS"; '
        'printf "vertex=%s\\n" "$STRIX_VERTEX_FALLBACK_MODELS"'
    )
    return subprocess.run(
        [bash(), "-c", command],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_strix_policy_adds_free_nim_fallbacks_before_github_quota(
    tmp_path: Path,
) -> None:
    """Public NIM scans exhaust multiple free NIM models before other tiers."""
    fixture = prepare_strix_fixture(tmp_path)
    fixture["primary"].write_text(
        "nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b", encoding="utf-8"
    )
    result = run_strix_source(
        fixture,
        plan=(
            "nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b "
            "nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1.5 "
            "nvidia_nim/nvidia/nemotron-3-super-120b-a12b "
            "github_models/openai/o3"
        ),
        extra_env={"STRIX_FALLBACK_MODELS": "github_models/openai/o3"},
    )
    assert result.returncode == 0, result.stderr
    lines = dict(line.split("=", 1) for line in result.stdout.splitlines())
    assert lines["primary"] == "nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b"
    assert lines["fallback"].split()[:2] == [
        "nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "nvidia_nim/nvidia/nemotron-3-super-120b-a12b",
    ]
    assert lines["fallback"] == lines["vertex"]


def test_strix_policy_moves_github_free_quota_before_paid_primary(
    tmp_path: Path,
) -> None:
    """Private direct-OpenAI scans use configured GitHub free quota first."""
    fixture = prepare_strix_fixture(tmp_path)
    fixture["primary"].write_text("openai_direct/gpt-5.6-luna", encoding="utf-8")
    result = run_strix_source(
        fixture,
        plan=(
            "github_models/openai/o3 github_models/openai/gpt-5-chat "
            "openai_direct/gpt-5.6-luna"
        ),
        extra_env={
            "STRIX_FALLBACK_MODELS": (
                "github_models/openai/o3 github_models/openai/gpt-5-chat"
            )
        },
    )
    assert result.returncode == 0, result.stderr
    lines = dict(line.split("=", 1) for line in result.stdout.splitlines())
    assert lines["primary"] == "github_models/openai/o3"
    assert lines["fallback"].split() == [
        "github_models/openai/gpt-5-chat",
        "openai_direct/gpt-5.6-luna",
    ]


def test_strix_policy_maps_generic_primary_alias_and_deduplicates(
    tmp_path: Path,
) -> None:
    """Future approved primary names retain identity while using shared cost order."""
    fixture = prepare_strix_fixture(tmp_path)
    fixture["primary"].write_text("openai_direct/gpt-6", encoding="utf-8")
    result = run_strix_source(
        fixture,
        plan="github_models/openai/o3 configured/strix-paid-primary",
        extra_env={"STRIX_FALLBACK_MODELS": "github_models/openai/o3"},
    )
    assert result.returncode == 0, result.stderr
    lines = dict(line.split("=", 1) for line in result.stdout.splitlines())
    assert lines == {
        "primary": "github_models/openai/o3",
        "fallback": "openai_direct/gpt-6",
        "vertex": "openai_direct/gpt-6",
    }


def test_strix_utils_do_not_invoke_policy_without_model_file(tmp_path: Path) -> None:
    """Standalone helper-function tests remain side-effect free."""
    fixture = prepare_strix_fixture(tmp_path)
    env = os.environ.copy()
    env.update({"SCRIPT_DIR": str(fixture["utils"].parent)})
    env.pop("STRIX_LLM_FILE", None)
    result = subprocess.run(
        [
            bash(),
            "-c",
            f'source "{fixture["utils"]}"; normalize_model "model"',
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "vertex_ai/model"


@pytest.mark.parametrize(
    ("extra_env", "primary", "message"),
    [
        ({"STRIX_REPOSITORY_VISIBILITY": "secret"}, "openai_direct/gpt-5.6-luna", "must be public"),
        ({"FAKE_POLICY_FAIL": "1"}, "openai_direct/gpt-5.6-luna", "could not be created"),
        ({}, "bad model", "invalid model token"),
    ],
)
def test_strix_policy_fails_closed(
    tmp_path: Path, extra_env: dict[str, str], primary: str, message: str
) -> None:
    """Invalid visibility, policy failure, and unsafe model tokens stop the gate."""
    fixture = prepare_strix_fixture(tmp_path)
    fixture["primary"].write_text(primary, encoding="utf-8")
    result = run_strix_source(fixture, plan="", extra_env=extra_env)
    assert result.returncode == 2
    assert message in result.stderr
