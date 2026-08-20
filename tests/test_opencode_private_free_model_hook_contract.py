"""The live model-pool runner must source the private free-model hook."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
RUNNER = REPO / "scripts" / "ci" / "run_opencode_review_model_pool.sh"
HOOK = REPO / "scripts" / "ci" / "opencode_private_free_model_hook.sh"
POLICY = REPO / "scripts" / "ci" / "opencode_private_free_model_policy.py"
GUARD = REPO / "scripts" / "ci" / "opencode_provider_guard.sh"
WORKFLOW = REPO / ".github" / "workflows" / "opencode-review-dispatch.yml"
POLICY_PATH = Path(".github/opencode-private-free-models.json")
GOVERNED = "opencode-free/nemotron-3-ultra-free"
STALE_FREE = "opencode-free/stale-free"
KEYED = "openai/gpt-5.6-luna"
VALID_POLICY = {
    "schema_version": 1,
    "allow_private_free_models": True,
    "repository_data_classification": "public_equivalent",
    "external_model_data_use_accepted": True,
}


def test_live_runner_sources_private_free_model_hook() -> None:
    """Private free-model opt-in is a hook, not a replacement runner."""

    runner = RUNNER.read_text(encoding="utf-8")
    hook = HOOK.read_text(encoding="utf-8")
    assert "opencode_private_free_model_hook.sh" in runner
    assert "apply_private_free_model_policy" in runner
    assert "maybe_enable_private_free_models" in hook
    assert "install_provider_guard" in hook
    assert "-u COPILOT_GITHUB_TOKEN" in hook
    assert POLICY.is_file()
    assert GUARD.is_file()
    assert "run_opencode_review_model_pool_impl.sh" not in runner


def test_live_model_pool_step_exports_trusted_visibility_and_base_sha() -> None:
    """Production must export trusted visibility next to PR_BASE_SHA."""

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert (
        "OPENCODE_REPOSITORY_IS_PRIVATE: ${{ needs.validate-pr-metadata.outputs.is_private }}"
        in workflow
    )
    assert "PR_BASE_SHA: ${{ needs.validate-pr-metadata.outputs.base_sha }}" in workflow


def bash_command() -> str:
    """Return a Bash executable that can source the production hook."""
    found = shutil.which("bash")
    if found:
        return found
    raise RuntimeError("bash executable was not found")


def run_hook(
    tmp_path: Path,
    *,
    extra_env: dict[str, str],
    source_workdir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Apply the production hook and return the resulting candidate list."""
    env = os.environ.copy()
    env.pop("OPENCODE_REPOSITORY_IS_PRIVATE", None)
    env.pop("PR_BASE_SHA", None)
    env.pop("PR_HEAD_SHA", None)
    env.pop("HEAD_SHA", None)
    env.pop("OPENCODE_SOURCE_WORKDIR", None)
    env["OPENCODE_MODEL_CANDIDATES"] = f"{GOVERNED} {STALE_FREE} {KEYED}"
    if source_workdir is not None:
        env["OPENCODE_SOURCE_WORKDIR"] = str(source_workdir)
    env.update(extra_env)
    script = f"""
set -euo pipefail
. {HOOK.as_posix()}
apply_private_free_model_policy
printf '%s\\n' "${{OPENCODE_MODEL_CANDIDATES-}}"
"""
    return subprocess.run(
        [bash_command(), "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def candidate_list(result: subprocess.CompletedProcess[str]) -> list[str]:
    """Return the hook's final candidate tokens, ignoring policy explain text."""
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert lines, result.stdout + result.stderr
    return lines[-1].split()


def git(repo: Path, *args: str) -> str:
    """Run Git in an isolated fixture repository and return stdout."""
    env = os.environ.copy()
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "OpenCode Hook Test",
            "GIT_AUTHOR_EMAIL": "opencode-hook@example.invalid",
            "GIT_COMMITTER_NAME": "OpenCode Hook Test",
            "GIT_COMMITTER_EMAIL": "opencode-hook@example.invalid",
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "user.name",
            "GIT_CONFIG_VALUE_0": "OpenCode Hook Test",
            "GIT_CONFIG_KEY_1": "user.email",
            "GIT_CONFIG_VALUE_1": "opencode-hook@example.invalid",
        }
    )
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def write_policy(repo: Path) -> None:
    """Write the exact trusted-base private free-model policy document."""
    path = repo / POLICY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(VALID_POLICY, indent=2) + "\n", encoding="utf-8")


def test_public_visibility_keeps_governed_aliases_and_drops_stale(
    tmp_path: Path,
) -> None:
    """Public visibility keeps governed aliases and drops stale free names."""
    result = run_hook(
        tmp_path,
        extra_env={"OPENCODE_REPOSITORY_IS_PRIVATE": "false"},
    )
    assert result.returncode == 0, result.stderr
    candidates = candidate_list(result)
    assert GOVERNED in candidates
    assert KEYED in candidates
    assert STALE_FREE not in candidates


def test_private_visibility_without_base_policy_strips_free_aliases(
    tmp_path: Path,
) -> None:
    """Private visibility with no base policy strips every free alias."""
    repo = tmp_path / "private-repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "initial")
    head = git(repo, "rev-parse", "HEAD")
    result = run_hook(
        tmp_path,
        source_workdir=repo,
        extra_env={
            "OPENCODE_REPOSITORY_IS_PRIVATE": "true",
            "PR_BASE_SHA": head,
            "PR_HEAD_SHA": head,
        },
    )
    assert result.returncode == 0, result.stderr
    candidates = candidate_list(result)
    assert candidates == [KEYED]
    assert GOVERNED not in candidates
    assert STALE_FREE not in candidates


def test_unchanged_eligible_base_policy_prepends_governed_catalog(
    tmp_path: Path,
) -> None:
    """An unchanged eligible base policy prepends the governed catalog."""
    repo = tmp_path / "eligible-repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "initial")
    write_policy(repo)
    git(repo, "add", str(POLICY_PATH))
    git(repo, "commit", "-m", "trusted policy")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "NOTE.md").write_text("unrelated\n", encoding="utf-8")
    git(repo, "add", "NOTE.md")
    git(repo, "commit", "-m", "unrelated head")
    head = git(repo, "rev-parse", "HEAD")
    result = run_hook(
        tmp_path,
        source_workdir=repo,
        extra_env={
            "OPENCODE_REPOSITORY_IS_PRIVATE": "true",
            "PR_BASE_SHA": base,
            "PR_HEAD_SHA": head,
        },
    )
    assert result.returncode == 0, result.stderr
    candidates = candidate_list(result)
    assert candidates[0] == GOVERNED
    assert KEYED in candidates
    assert STALE_FREE not in candidates
    assert "opencode-free/deepseek-v4-flash-free" in candidates


def test_malformed_visibility_fails_closed_to_policy_path(tmp_path: Path) -> None:
    """Malformed visibility is not public and requires the trusted-base policy."""
    repo = tmp_path / "malformed-repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "initial")
    head = git(repo, "rev-parse", "HEAD")
    result = run_hook(
        tmp_path,
        source_workdir=repo,
        extra_env={
            "OPENCODE_REPOSITORY_IS_PRIVATE": "maybe",
            "PR_BASE_SHA": head,
            "PR_HEAD_SHA": head,
        },
    )
    assert result.returncode == 0, result.stderr
    candidates = candidate_list(result)
    assert candidates == [KEYED]
    assert "visibility input is invalid" in result.stderr
