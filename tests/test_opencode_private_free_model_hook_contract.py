"""The live model-pool runner must source and obey the private free-model hook."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
RUNNER = REPO / "scripts" / "ci" / "run_opencode_review_model_pool.sh"
HOOK = REPO / "scripts" / "ci" / "opencode_private_free_model_hook.sh"
POLICY = REPO / "scripts" / "ci" / "opencode_private_free_model_policy.py"
GUARD = REPO / "scripts" / "ci" / "opencode_provider_guard.sh"
WORKFLOW = REPO / ".github" / "workflows" / "opencode-review-dispatch.yml"
POLICY_PATH = Path(".github/opencode-private-free-models.json")
VALID_POLICY = {
    "schema_version": 1,
    "allow_private_free_models": True,
    "repository_data_classification": "public_equivalent",
    "external_model_data_use_accepted": True,
}
GOVERNED_FREE = "opencode-free/nemotron-3-ultra-free"
STALE_FREE = "opencode-free/glm-5-free"
KEYED = "opencode/gpt-5.6-terra"


def test_live_runner_sources_private_free_model_hook() -> None:
    """Private free-model opt-in is a hook, not a replacement runner."""

    runner = RUNNER.read_text(encoding="utf-8")
    hook = HOOK.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "opencode_private_free_model_hook.sh" in runner
    assert "apply_private_free_model_policy" in runner
    assert "maybe_enable_private_free_models" in hook
    assert "install_provider_guard" in hook
    assert "OPENCODE_TRUSTED_SOURCE_DIR" in hook
    assert POLICY.is_file()
    assert GUARD.is_file()
    assert "run_opencode_review_model_pool_impl.sh" not in runner
    assert (
        "OPENCODE_REPOSITORY_IS_PRIVATE: "
        "${{ needs.validate-pr-metadata.outputs.is_private }}"
    ) in workflow
    assert "PR_BASE_SHA: ${{ needs.validate-pr-metadata.outputs.base_sha }}" in workflow
    assert "OPENCODE_TRUSTED_SOURCE_DIR: ${{ github.workspace }}" in workflow


def run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with deterministic Git identity and no global config."""
    env = os.environ.copy()
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "OpenCode Hook Test",
            "GIT_AUTHOR_EMAIL": "opencode-hook@example.invalid",
            "GIT_COMMITTER_NAME": "OpenCode Hook Test",
            "GIT_COMMITTER_EMAIL": "opencode-hook@example.invalid",
        }
    )
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def git(repo: Path, *args: str) -> str:
    """Run Git and return stripped stdout, failing the test on errors."""
    result = run("git", *args, cwd=repo)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def commit_all(repo: Path, message: str) -> str:
    """Commit every tracked and untracked fixture and return its SHA."""
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def create_repository(tmp_path: Path, *, with_policy: bool) -> tuple[Path, str, str]:
    """Create one isolated Git repository and return it with base and head SHAs."""
    repo = tmp_path / "repository"
    repo.mkdir()
    git(repo, "init", "--initial-branch=main")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    if with_policy:
        policy = repo / POLICY_PATH
        policy.parent.mkdir(parents=True, exist_ok=True)
        policy.write_text(json.dumps(VALID_POLICY, indent=2) + "\n", encoding="utf-8")
    base_sha = commit_all(repo, "base")
    (repo / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
    head_sha = commit_all(repo, "code change")
    return repo, base_sha, head_sha


def run_hook(
    tmp_path: Path,
    *,
    candidates: str,
    extra_env: dict[str, str] | None = None,
    function: str = "maybe_enable_private_free_models",
) -> subprocess.CompletedProcess[str]:
    """Source the real hook and print the resulting candidate list."""
    script = tmp_path / "run-hook.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f". {HOOK.as_posix()}\n"
        f"policy_checker={POLICY.as_posix()}\n"
        f"provider_guard={GUARD.as_posix()}\n"
        f"{function}\n"
        'printf "CANDIDATES=%s\\n" "${OPENCODE_MODEL_CANDIDATES:-}"\n',
        encoding="utf-8",
    )
    script.chmod(0o755)
    env = os.environ.copy()
    for name in (
        "HEAD_SHA",
        "OPENCODE_REPOSITORY_IS_PRIVATE",
        "OPENCODE_SOURCE_WORKDIR",
        "OPENCODE_TRUSTED_SOURCE_DIR",
        "PR_BASE_SHA",
        "PR_HEAD_SHA",
    ):
        env.pop(name, None)
    env["OPENCODE_MODEL_CANDIDATES"] = candidates
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(script)],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def candidates_from(result: subprocess.CompletedProcess[str]) -> str:
    """Return the hook's exported candidate list from a successful run."""
    assert result.returncode == 0, result.stdout + result.stderr
    for line in result.stdout.splitlines():
        if line.startswith("CANDIDATES="):
            return line.removeprefix("CANDIDATES=")
    raise AssertionError(f"hook did not print candidates: {result.stdout}")


def test_public_visibility_keeps_governed_free_and_drops_stale_aliases(
    tmp_path: Path,
) -> None:
    """Public callers may keep only the current zero-cost catalog."""
    result = run_hook(
        tmp_path,
        candidates=f"{STALE_FREE} {GOVERNED_FREE} {KEYED}",
        extra_env={"OPENCODE_REPOSITORY_IS_PRIVATE": "false"},
    )

    assert candidates_from(result) == f"{GOVERNED_FREE} {KEYED}"


def test_private_preconfigured_free_candidates_are_removed_without_policy(
    tmp_path: Path,
) -> None:
    """Private callers cannot inherit opencode-free aliases before policy approval."""
    repo, base_sha, head_sha = create_repository(tmp_path, with_policy=False)
    result = run_hook(
        tmp_path,
        candidates=f"{GOVERNED_FREE} {STALE_FREE} {KEYED}",
        extra_env={
            "OPENCODE_REPOSITORY_IS_PRIVATE": "true",
            "OPENCODE_SOURCE_WORKDIR": str(repo),
            "PR_BASE_SHA": base_sha,
            "PR_HEAD_SHA": head_sha,
        },
    )

    assert candidates_from(result) == KEYED
    assert GOVERNED_FREE not in result.stdout
    assert STALE_FREE not in result.stdout


def test_private_unchanged_base_policy_prepends_governed_free_candidates(
    tmp_path: Path,
) -> None:
    """An eligible trusted-base policy is the only private re-enable path."""
    repo, base_sha, head_sha = create_repository(tmp_path, with_policy=True)
    result = run_hook(
        tmp_path,
        candidates=KEYED,
        extra_env={
            "OPENCODE_REPOSITORY_IS_PRIVATE": "true",
            "OPENCODE_SOURCE_WORKDIR": str(repo),
            "PR_BASE_SHA": base_sha,
            "PR_HEAD_SHA": head_sha,
        },
    )

    exported = candidates_from(result)
    assert exported.startswith(GOVERNED_FREE)
    assert KEYED in exported.split()
    assert STALE_FREE not in exported
    assert "Enabled governed anonymous OpenCode free-model candidates" in result.stdout


def test_invalid_visibility_fails_closed_to_the_policy_path(tmp_path: Path) -> None:
    """Malformed visibility is not public evidence and cannot keep free aliases."""
    result = run_hook(
        tmp_path,
        candidates=f"{GOVERNED_FREE} {KEYED}",
        extra_env={"OPENCODE_REPOSITORY_IS_PRIVATE": "maybe"},
    )

    assert candidates_from(result) == KEYED
    assert "invalid" in result.stderr.casefold()


def test_apply_without_visibility_or_base_sha_preserves_direct_candidates(
    tmp_path: Path,
) -> None:
    """Local unit tests that omit both live signals keep their explicit candidate list."""
    result = run_hook(
        tmp_path,
        candidates=f"{GOVERNED_FREE} {KEYED}",
        function="apply_private_free_model_policy",
    )

    assert candidates_from(result) == f"{GOVERNED_FREE} {KEYED}"
