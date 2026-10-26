"""Exercise the actual Strix materializers with real local Git repositories."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/strix.yml"
ALLOCATE = "Allocate this job's target workspace"
CLEANUP = "Clean up this job's target workspace"
MATERIALIZERS = (
    "Materialize target workspace",
    "Validate repository dispatch against live pull request metadata",
)


def _step(name: str) -> str:
    """Read the exact shell, without substituting Git or workspace operations."""
    marker = f"      - name: {name}\n"
    source = WORKFLOW.read_text()
    if marker not in source:
        return ""
    block = source.split(marker, 1)[1].split("      - name:", 1)[0]
    return textwrap.dedent(block.split("        run: |\n", 1)[1])


def _git(root: Path, env: dict[str, str], *args: str) -> str:
    """Use real Git with fixture-local identity and no hooks/signing."""
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
         "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
         "-C", str(root), *args],
        env=env, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _shell(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Only GitHub auth/API are finite external IO; Git is never intercepted."""
    boundary = '''gh() {
      if [[ "$*" == "auth setup-git" ]]; then return 0; fi
      if [[ "$*" == "api repos/ContextualWisdomLab/.github/pulls/7" ]]; then
        printf '%s\\n' "$FIXTURE_PR_JSON"
        return 0
      fi
      printf 'unexpected GitHub operation\\n' >&2
      return 97
    }
    '''
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c",
         textwrap.dedent(boundary) + script],
        env=env, text=True, capture_output=True,
    )


def _apply_environment(env: dict[str, str]) -> None:
    """Emulate only the runner's next-step environment-file import."""
    for line in Path(env["GITHUB_ENV"]).read_text().splitlines():
        key, value = line.split("=", 1)
        env[key] = value


@pytest.fixture
def workspace_fixture(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    """Build a real committed origin and a stale repo that must stay untouched."""
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
               GIT_TERMINAL_PROMPT="0")
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, env, "init", "--quiet")
    (seed / "source.txt").write_text("exact trusted base\n")
    _git(seed, env, "add", "source.txt")
    _git(seed, env, "commit", "--quiet", "-m", "trusted base")
    sha = _git(seed, env, "rev-parse", "HEAD")
    remotes = tmp_path / "remotes"
    remote = remotes / "ContextualWisdomLab/.github.git"
    remote.parent.mkdir(parents=True)
    _git(seed, env, "clone", "--bare", "--quiet", str(seed), str(remote))
    runner = tmp_path / "runner"
    runner.mkdir()
    stale = runner / "trusted-workspace"
    stale.mkdir()
    _git(stale, env, "init", "--quiet")
    _git(stale, env, "remote", "add", "origin", "https://previous.invalid/repo.git")
    (stale / "unrelated.txt").write_text("do not clean or reuse\n")
    environment_file = tmp_path / "environment"
    environment_file.touch()
    env.update(RUNNER_TEMP=str(runner), GITHUB_ENV=str(environment_file),
               GITHUB_SERVER_URL=remotes.as_uri(), REPOSITORY="ContextualWisdomLab/.github",
               TARGET_WORKSPACE_SHA=sha, PR_NUMBER="7", SUPPLIED_BASE_REF="main",
               SUPPLIED_BASE_SHA=sha, SUPPLIED_HEAD_SHA=sha)
    env["FIXTURE_PR_JSON"] = json.dumps({
        "state": "open", "base": {"ref": "main", "sha": sha,
            "repo": {"full_name": env["REPOSITORY"]}},
        "head": {"sha": sha, "repo": {"full_name": env["REPOSITORY"]}},
    })
    return env, stale, remote


def _materialize(env: dict[str, str], name: str) -> subprocess.CompletedProcess[str]:
    """Execute old or new workflow bytes, preserving the original RED path."""
    allocation = _step(ALLOCATE)
    if allocation:
        result = _shell(allocation, env)
        assert result.returncode == 0, result.stderr
        _apply_environment(env)
    return _shell(_step(name), env)


@pytest.mark.parametrize("name", MATERIALIZERS)
def test_repeated_materialization_is_job_private_and_cleanup_is_owned(
    name: str, workspace_fixture: tuple[dict[str, str], Path, Path]
) -> None:
    """An old origin cannot break a fresh scan or authorize a shared sweep."""
    env, stale, remote = workspace_fixture
    stale_config = (stale / ".git/config").read_bytes()
    workspaces = []
    for _ in range(2):
        step_env = dict(env)
        result = _materialize(step_env, name)
        assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
        _apply_environment(step_env)
        workspace = Path(step_env["TRUSTED_WORKSPACE"])
        assert workspace.parent == Path(env["RUNNER_TEMP"])
        assert workspace.name.startswith("strix-workspace-")
        assert workspace != stale
        assert _git(workspace, step_env, "rev-parse", "HEAD") == env["TARGET_WORKSPACE_SHA"]
        assert _git(workspace, step_env, "remote", "get-url", "origin") == remote.as_uri()
        assert (workspace / "source.txt").read_text() == "exact trusted base\n"
        assert not (workspace / "unrelated.txt").exists()
        workspaces.append((workspace, step_env))
    assert workspaces[0][0] != workspaces[1][0]
    assert all(path.is_dir() for path, _ in workspaces)
    cleanup = _step(CLEANUP)
    assert cleanup, "owned workspace cleanup is required"
    first, first_env = workspaces[0]
    result = _shell(cleanup, first_env)
    assert result.returncode == 0, result.stderr
    assert not first.exists()
    assert workspaces[1][0].is_dir()
    result = _shell(cleanup, first_env)
    assert result.returncode == 0, result.stderr
    result = _shell(cleanup, workspaces[1][1])
    assert result.returncode == 0, result.stderr
    assert (stale / ".git/config").read_bytes() == stale_config
    assert (stale / "unrelated.txt").read_text() == "do not clean or reuse\n"


@pytest.mark.parametrize("case", ("old-root", "symlink", "identity"))
def test_cleanup_refuses_unowned_or_replaced_workspace(
    case: str, workspace_fixture: tuple[dict[str, str], Path, Path]
) -> None:
    """A changed locator cannot delete a neighbor, replacement or symlink target."""
    env, stale, _ = workspace_fixture
    result = _shell(_step(ALLOCATE), env)
    assert result.returncode == 0, result.stderr
    _apply_environment(env)
    root = Path(env["TRUSTED_WORKSPACE"])
    sentinel = stale / "unrelated.txt"
    if case == "old-root":
        env["TRUSTED_WORKSPACE"] = str(stale)
    elif case == "symlink":
        root.rmdir()
        root.symlink_to(stale, target_is_directory=True)
    else:
        env["TRUSTED_WORKSPACE_INODE"] = str(int(env["TRUSTED_WORKSPACE_INODE"]) + 1)
    result = _shell(_step(CLEANUP), env)
    assert result.returncode != 0
    assert "refusing" in result.stderr
    assert sentinel.read_text() == "do not clean or reuse\n"
    assert root.exists()


def test_materialization_failure_still_allows_only_owned_cleanup(
    workspace_fixture: tuple[dict[str, str], Path, Path]
) -> None:
    """Publish ownership before fetch so failure cannot strand a fixed repo."""
    env, stale, _ = workspace_fixture
    env["TARGET_WORKSPACE_SHA"] = "f" * 40
    result = _materialize(env, MATERIALIZERS[0])
    assert result.returncode != 0
    root = Path(env["TRUSTED_WORKSPACE"])
    assert root.is_dir()
    cleanup_block = WORKFLOW.read_text().split(f"      - name: {CLEANUP}\n", 1)[1]
    assert "if: always() && env.TRUSTED_WORKSPACE != ''" in cleanup_block.split("        run: |", 1)[0]
    result = _shell(_step(CLEANUP), env)
    assert result.returncode == 0, result.stderr
    assert not root.exists()
    assert (stale / "unrelated.txt").exists()


def test_dispatch_metadata_mismatch_still_fails_before_git_init(
    workspace_fixture: tuple[dict[str, str], Path, Path]
) -> None:
    """A private root does not relax the existing live PR identity fence."""
    env, stale, _ = workspace_fixture
    env["SUPPLIED_HEAD_SHA"] = "f" * 40
    result = _materialize(env, MATERIALIZERS[1])
    assert result.returncode != 0
    assert "does not match live PR" in result.stdout
    root = Path(env["TRUSTED_WORKSPACE"])
    assert not (root / ".git").exists()
    assert (stale / "unrelated.txt").exists()
    result = _shell(_step(CLEANUP), env)
    assert result.returncode == 0, result.stderr
    assert not root.exists()


def test_workspace_regression_is_enrolled_in_quality_ci() -> None:
    """The real Git regression must not remain a manually invoked orphan."""
    quality = (ROOT / ".github/workflows/agent-review-runtime-quality-ci.yml").read_text()
    path = "tests/test_strix_workspace_isolation.py"
    trigger = quality.split("on:\n", 1)[1].split("\nconcurrency:\n", 1)[0]
    assert f'      - "{path}"' in trigger
    selector = quality.split('            case "$changed_path" in\n', 1)[1].split("            esac", 1)[0]
    result = _shell('changed_path=' + path + '\nstrix_suite=false\ncase "$changed_path" in\n'
                    + selector + 'esac\ntest "$strix_suite" = true\n', dict(os.environ))
    assert result.returncode == 0, result.stderr
    verify = quality.split("- name: Verify exact-head path policy and syntax", 1)[1].split("      - name:", 1)[0]
    assert "if: steps.affected_suites.outputs.strix == 'true'" in verify
    assert path in verify.split("python -m compileall", 1)[0]
    assert path in verify.split("python -m compileall", 1)[1]


def test_scan_uses_allocated_workspace_without_weakening_scope_or_threshold() -> None:
    """Only the root locator changes; trusted execution and scan policy remain."""
    source = WORKFLOW.read_text()
    step = source.split("      - name: Run Strix (quick)\n", 1)[1].split("      - name:", 1)[0]
    assert "working-directory: ${{ env.TRUSTED_WORKSPACE }}" in step
    assert "STRIX_REPO_ROOT: ${{ env.TRUSTED_WORKSPACE }}" in step
    assert "STRIX_FAIL_ON_MIN_SEVERITY: MEDIUM" in step
    assert "&& '__PR_SCOPE__' || './'" in step
    assert 'bash "$TRUSTED_STRIX_GATE"' in step
    assert "STRIX_FAIL_ON_PROVIDER_SIGNAL: \"1\"" in step
