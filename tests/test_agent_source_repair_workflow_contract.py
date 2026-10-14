"""Static security and architecture contracts for the explicit source-repair workflow."""
from pathlib import Path
import os
import re
import subprocess
import textwrap

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "agent-source-repair.yml"


def _job_names(text: str) -> set[str]:
    """Return top-level job keys without requiring a YAML runtime dependency."""
    jobs_text = text.split("\njobs:\n", 1)[1]
    return set(re.findall(r"^  ([A-Za-z0-9_-]+):\s*$", jobs_text, flags=re.MULTILINE))


def _job_block(text: str, job_name: str) -> str:
    """Return one top-level job block from the workflow source text."""
    jobs_text = text.split("\njobs:\n", 1)[1]
    marker = f"  {job_name}:\n"
    block = jobs_text.split(marker, 1)[1]
    next_job = re.search(r"^  [A-Za-z0-9_-]+:\s*$", block, flags=re.MULTILINE)
    return block[: next_job.start()] if next_job else block


def test_source_repair_worker_uses_only_contextual_orchestrator_free() -> None:
    """The model-backed mutation lane must not select a provider/model or paid fallback."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "contextual-orchestrator/orchestrator/free" in text
    assert "nvidia-nim/" not in text.lower()
    assert "openrouter/" not in text.lower()
    assert "openai/" not in text.lower()
    assert "--force" not in text
    assert "core.hooksPath=/dev/null push" in text


def test_source_repair_has_separate_sweep_and_serial_writer() -> None:
    """Discovery may recur, while one target PR has exactly one mutation writer at a time."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert _job_names(text) == {"sweep-source-repair-comments", "source-repair"}
    source_repair = _job_block(text, "source-repair")
    assert "    concurrency:\n" in source_repair
    assert "      cancel-in-progress: false\n" in source_repair
    assert "target_repository" in source_repair and "pr_number" in source_repair
    assert "    timeout-minutes:" not in source_repair


def test_worker_revalidates_before_normal_push() -> None:
    """Mutation requires a second authority/scope check immediately before publication."""
    text = WORKFLOW.read_text(encoding="utf-8")
    step = text.split("- name: Revalidate authority and push a normal commit", 1)[1]
    assert "agent_source_repair.py" in step
    assert "cmp \"$RUNNER_TEMP/agent-source-repair-allowed-paths.zlist\"" in step
    assert "live_head" in step
    assert "git -c core.hooksPath=/dev/null push" in step
    assert "merge" not in step.lower()


def test_worker_validates_changed_yaml_before_publication() -> None:
    """A model-edited YAML file must parse successfully before any source-repair commit is pushed."""
    text = WORKFLOW.read_text(encoding="utf-8")
    validation = text.split("- name: Validate resulting diff", 1)[1].split(
        "- name: Revalidate authority and push a normal commit", 1
    )[0]
    assert 'case "$changed_file" in *.yml|*.yaml)' in validation
    assert "YAML.parse_file" in validation


def test_quality_installs_the_locked_document_dependency() -> None:
    """Full-suite collection must receive the document parser's pinned dependency."""
    text = (ROOT / ".github/workflows/agent-source-repair-quality-ci.yml").read_text(
        encoding="utf-8"
    )
    lock = "requirements-noema-document-ci-hashes.txt"
    assert f"-r {lock}" in text
    assert text.count(f'      - "{lock}"') == 2
    cache = text.split("cache-dependency-path:", 1)[1].split("- name:", 1)[0]
    assert lock in cache


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    """Create a repository without ignore rules and a sealed single-file scope."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "src").mkdir()
    (workspace / "src/main.py").write_text("VALUE = 1\n")
    for args in (
        ["init"], ["config", "user.name", "Test"],
        ["config", "user.email", "test@example.invalid"],
    ):
        subprocess.run(["git", "-C", str(workspace), *args], check=True, capture_output=True)
    runner_temp = tmp_path / "runner"
    runner_temp.mkdir()
    (runner_temp / "agent-source-repair-allowed-paths.zlist").write_bytes(b"src/main.py\0")
    return workspace, runner_temp


def _step_script(name: str, next_name: str | None = None) -> str:
    """Extract the actual shell body of one trusted workflow step."""
    block = WORKFLOW.read_text().split(f"- name: {name}\n", 1)[1]
    if next_name is not None:
        block = block.split(f"- name: {next_name}\n", 1)[0]
    return textwrap.dedent(block.split("run: |\n", 1)[1])


@pytest.mark.parametrize("shadow_module", [False, True])
def test_python_validation_stays_outside_workspace(tmp_path: Path, shadow_module: bool) -> None:
    """Compilation must create no unsealed bytecode or execute a PR-owned module."""
    workspace, runner_temp = _workspace(tmp_path)
    marker = runner_temp / "shadow-executed"
    if shadow_module:
        (workspace / "py_compile.py").write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
        )
    subprocess.run(["git", "-C", str(workspace), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(workspace), "commit", "-m", "base"], check=True, capture_output=True)
    (workspace / "src/main.py").write_text("VALUE = 2\n")
    env = {**os.environ, "TARGET_WORKSPACE": str(workspace), "RUNNER_TEMP": str(runner_temp)}
    env.pop("PYTHONPYCACHEPREFIX", None)
    script = _step_script("Validate resulting diff", "Revalidate authority and push a normal commit")
    result = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not marker.exists()
    assert list(workspace.rglob("*.pyc")) == []


@pytest.mark.parametrize("extra_path", [None, "unsealed.txt"])
def test_final_staging_checks_every_path(tmp_path: Path, extra_path: str | None) -> None:
    """A late unsealed file must block publication after git add, not before it."""
    workspace, runner_temp = _workspace(tmp_path)
    if extra_path is not None:
        (workspace / extra_path).write_text("late change\n")
    script = _step_script("Revalidate authority and push a normal commit")
    staging = "set -euo pipefail\ngit add -A\n" + script.split("git add -A\n", 1)[1].split(
        "git -c core.hooksPath=/dev/null commit", 1
    )[0]
    result = subprocess.run(
        ["bash", "-c", staging], cwd=workspace,
        env={**os.environ, "RUNNER_TEMP": str(runner_temp)}, capture_output=True, text=True,
    )
    assert (result.returncode == 0) is (extra_path is None), result.stdout + result.stderr


def test_review_mentions_remain_separate_from_source_mutation() -> None:
    """The source writer is a distinct command path and does not weaken review workflows."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "types: [agent-source-repair]" in text
    assert "@opencode-agent" not in text
    assert "agent-mention-opencode" not in text
