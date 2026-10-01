"""Keep the self-hosted OpenCode coverage runner usable between jobs.

On 2026-09-29 `cwlab-s1-04` filled its disk twice with per-job coverage images,
and every Rust coverage run failed because `cargo` lives in `~/.cargo/bin`,
which the runner service does not put on PATH.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github/workflows/opencode-review-dispatch.yml"


def _steps() -> list[dict]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["coverage-evidence"]["steps"]


def _step(name: str) -> dict:
    return next(s for s in _steps() if s.get("name") == name)


def _index(name: str) -> int:
    return next(i for i, s in enumerate(_steps()) if s.get("name") == name)


def _run(script: str, tmp_path: Path, *, home: Path, path_dirs: list[Path]) -> subprocess.CompletedProcess:
    github_path = tmp_path / "github_path"
    github_path.touch()
    env = {
        "HOME": str(home),
        "PATH": os.pathsep.join([*map(str, path_dirs), "/usr/bin", "/bin"]),
        "GITHUB_PATH": str(github_path),
    }
    return subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)


def _fake(bin_dir: Path, name: str, body: str) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    tool = bin_dir / name
    tool.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    tool.chmod(0o755)


def test_both_steps_run_before_coverage_measurement() -> None:
    measure = _index("Measure test and docstring evidence")
    assert _index("Reclaim stale coverage images") < measure
    assert _index("Expose runner Rust toolchain") < measure


def test_image_reclaim_targets_only_old_coverage_images(tmp_path: Path) -> None:
    calls = tmp_path / "calls"
    fake_bin = tmp_path / "bin"
    _fake(fake_bin, "docker", f'echo "$*" >> {calls}\n[ "$1 $2" = "image ls" ] && echo abc123\nexit 0\n')
    result = _run(_step("Reclaim stale coverage images")["run"], tmp_path, home=tmp_path, path_dirs=[fake_bin])
    assert result.returncode == 0, result.stderr
    log = calls.read_text(encoding="utf-8").splitlines()
    assert "image ls --filter reference=opencode-coverage-tools --filter until=2h --format {{.ID}}" in log
    assert "image rm -f abc123" in log
    assert "image prune -f" in log
    assert "builder prune -f --filter until=24h" in log
    assert not any("prune -a" in line or "system prune" in line for line in log)


def test_image_reclaim_failure_warns_without_blocking_coverage(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    _fake(fake_bin, "docker", "exit 1\n")
    result = _run(_step("Reclaim stale coverage images")["run"], tmp_path, home=tmp_path, path_dirs=[fake_bin])
    assert result.returncode == 0
    assert "::warning::" in result.stdout


def test_home_cargo_is_added_to_github_path(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _fake(home / ".cargo" / "bin", "cargo", "exit 0\n")
    result = _run(_step("Expose runner Rust toolchain")["run"], tmp_path, home=home, path_dirs=[])
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "github_path").read_text(encoding="utf-8") == f"{home}/.cargo/bin\n"


def test_cargo_already_on_path_is_left_alone(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    _fake(fake_bin, "cargo", "exit 0\n")
    result = _run(_step("Expose runner Rust toolchain")["run"], tmp_path, home=tmp_path / "home", path_dirs=[fake_bin])
    assert result.returncode == 0
    assert (tmp_path / "github_path").read_text(encoding="utf-8") == ""


def test_missing_cargo_warns_readably(tmp_path: Path) -> None:
    result = _run(_step("Expose runner Rust toolchain")["run"], tmp_path, home=tmp_path / "home", path_dirs=[])
    assert result.returncode == 0
    assert "::warning::cargo is not installed" in result.stdout


def test_reclaim_removes_only_old_coverage_workspaces(tmp_path: Path) -> None:
    """Root-owned sandbox workspaces left by earlier jobs are swept with sudo."""
    fake_bin = tmp_path / "bin"
    _fake(fake_bin, "docker", "exit 0\n")
    _fake(fake_bin, "sudo", 'exec "$@"\n')
    runner_temp = tmp_path / "runner_temp"
    old = runner_temp / "opencode-coverage-111-1"
    old_build = runner_temp / "opencode-coverage-tool-build-111-1"
    fresh = runner_temp / "opencode-coverage-222-1"
    current = runner_temp / "opencode-coverage-333-1"
    unrelated = runner_temp / "other-old"
    shared = [runner_temp / f"opencode-coverage-{n}" for n in ("artifact", "sandbox-result", "source", "tool-build")]
    for d in (old, old_build, fresh, current, unrelated, *shared):
        (d / "x").mkdir(parents=True)
    for d in (old, old_build, current, unrelated, *shared):
        os.utime(d, (0, 0))
    script = _step("Reclaim stale coverage images")["run"]
    result = subprocess.run(
        ["bash", "-c", script],
        env={"PATH": f"{fake_bin}:/usr/bin:/bin", "RUNNER_TEMP": str(runner_temp),
             "GITHUB_RUN_ID": "333", "HOME": str(tmp_path)},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not old.exists() and not old_build.exists()
    assert fresh.exists() and current.exists() and unrelated.exists()
    # Shared, non-run directories are never swept, however old.
    assert all(d.exists() for d in shared)
