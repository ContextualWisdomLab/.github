"""중앙 K-CSAP 품질 workflow 계약. 합성 메타데이터 테스트 전용."""
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CENTRAL = ROOT / ".github/workflows/k-csap-skills-quality.yml"


def workflow():
    assert CENTRAL.is_file()
    return yaml.safe_load(CENTRAL.read_text(encoding="utf-8"))


def test_reusable_only_and_no_hosted_fallback():
    obj = workflow()
    assert obj.get("on", obj.get(True)) == {"workflow_call": None}
    assert obj["permissions"] == {"contents": "read"}
    assert set(obj["jobs"]) == {"quality"}
    job = obj["jobs"]["quality"]
    assert job["name"] == "k-csap-skills-quality"
    assert job["runs-on"] == ["self-hosted", "Linux", "X64", "k-csap-isolated"]
    source = CENTRAL.read_text(encoding="utf-8")
    assert "ubuntu-latest" not in source and "ubuntu-24.04" not in source
    assert "secrets:" not in source and "continue-on-error" not in source
    assert "concurrency:" not in source
    assert job["timeout-minutes"] <= 20


def test_runner_assignment_admits_only_trusted_caller_before_lease():
    job = workflow()["jobs"]["quality"]
    gate = job["if"]
    assert "github.repository == 'ContextualWisdomLab/k-csap-skills'" in gate
    assert "github.event.pull_request.head.repo.full_name == github.repository" in gate
    assert "github.event.pull_request.state == 'open'" in gate
    assert "github.ref == 'refs/heads/master'" in gate
    assert "github.event_name == 'workflow_dispatch'" in gate
    assert "github.event_name == 'push'" in gate


def test_admission_before_checkout_and_no_credential_persistence():
    steps = workflow()["jobs"]["quality"]["steps"]
    assert steps[0]["id"] == "admission"
    text = steps[0]["run"]
    assert 'ContextualWisdomLab/k-csap-skills' in text
    assert 'pull_request' in text and 'push' in text and 'workflow_dispatch' in text
    assert 'exit 1' in text
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] is False
    assert checkout["with"]["path"].startswith("${{")
    assert "ref" in checkout["with"]
    assert steps[0]["env"]["TARGET_REPOSITORY"].startswith("${{")
    assert steps[0]["env"]["HEAD_REPOSITORY"].startswith("${{")


def test_locked_quality_steps_and_scope_are_executable():
    steps = workflow()["jobs"]["quality"]["steps"]
    source = "\n".join(step.get("run", "") for step in steps)
    for required in (
        "uv python install 3.11.14", "uv sync --locked --dev --python 3.11.14",
        "uv run --python 3.11.14 ruff check .", "uv run --python 3.11.14 pytest -q",
        "uv run --python 3.11.14 python scripts/validate.py", "git diff --check",
    ):
        assert required in source
    assert "set -euo pipefail" in source
    assert "git rev-parse HEAD" in source
    assert "RUNNER_TEMP" in source
    assert "trap " in source
    assert "UV_PYTHON_INSTALL_DIR" in source
    assert "UV_CACHE_DIR" in source


def test_checkout_preparation_and_cleanup_are_owned():
    steps = workflow()["jobs"]["quality"]["steps"]
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["path"] == "${{ steps.prepare.outputs.source_path }}"
    assert steps[0]["id"] == "admission"
    assert steps[1]["id"] == "prepare"
    cleanup = steps[-1]
    assert cleanup["if"] == "always()"
    assert "source_path" in cleanup["env"] or "SOURCE_PATH" in cleanup["env"]
    assert "rm -rf" in cleanup["run"]


@pytest.mark.parametrize("failed_at", ["success", "install", "test"])
def test_quality_shell_keeps_original_status_and_removes_private_runtime(tmp_path, failed_at):
    import os
    import subprocess

    steps = workflow()["jobs"]["quality"]["steps"]
    verify = next(step for step in steps if step.get("name", "").startswith("Verify K-CSAP"))
    script = verify["run"]
    work = tmp_path / "source"
    work.mkdir()
    (work / ".git").mkdir()
    sentinel = tmp_path / "untouched"
    sentinel.write_text("keep")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    marker = tmp_path / "marker"
    for name in ("uv", "git"):
        tool = bindir / name
        tool.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = rev-parse ]; then printf '%s\\n' \"$EXPECTED_SHA\"; exit 0; fi\n"
            "if [ \"$1\" = diff ]; then exit 0; fi\n"
            "if [ \"$1\" = python ] && [ \"$2\" = install ]; then : >\"$MARKER\"; fi\n"
            "if [ \"$FAIL_AT\" = install ] && [ \"$1\" = python ]; then exit 37; fi\n"
            "if [ \"$FAIL_AT\" = test ] && [ \"$1\" = run ] && "
            "[ \"$4\" = pytest ]; then exit 43; fi\n"
            "exit 0\n"
        )
        tool.chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "RUNNER_TEMP": str(tmp_path), "EXPECTED_SHA": "a" * 40,
           "MARKER": str(marker), "FAIL_AT": failed_at}
    proc = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                          cwd=work, env=env, capture_output=True, text=True, check=False)
    assert proc.returncode == {"success": 0, "install": 37, "test": 43}[failed_at], proc.stderr
    assert sentinel.read_text() == "keep"
    assert list(tmp_path.glob("k-csap-quality.*")) == []
    assert marker.exists()


@pytest.mark.parametrize(
    ("repository", "event", "head_repository", "expected_exit"),
    [
        ("ContextualWisdomLab/k-csap-skills", "push", "", 0),
        ("ContextualWisdomLab/k-csap-skills", "workflow_dispatch", "", 0),
        ("ContextualWisdomLab/k-csap-skills", "pull_request", "ContextualWisdomLab/k-csap-skills", 0),
        ("ContextualWisdomLab/k-csap-skills", "pull_request", "outside/fork", 1),
        ("ContextualWisdomLab/other", "push", "", 1),
        ("ContextualWisdomLab/k-csap-skills", "schedule", "", 1),
    ],
)
def test_actual_admission_shell_rejects_untrusted_before_checkout(
    repository, event, head_repository, expected_exit, tmp_path
):
    import os
    import subprocess

    script = workflow()["jobs"]["quality"]["steps"][0]["run"]
    env = {**os.environ, "TARGET_REPOSITORY": repository, "EVENT_NAME": event,
           "HEAD_REPOSITORY": head_repository, "EXPECTED_SHA": "a" * 40,
           "PR_STATE": "open", "EVENT_REF": "refs/heads/master",
           "GITHUB_OUTPUT": str(tmp_path / "output")}
    proc = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                          env=env, capture_output=True, text=True, check=False)
    assert proc.returncode == expected_exit, proc.stderr
    assert "Traceback" not in proc.stderr


@pytest.mark.parametrize("stale", [False, True])
def test_real_prepare_and_cleanup_preserve_stale_and_sibling_source(tmp_path, stale):
    import os
    import subprocess

    steps = workflow()["jobs"]["quality"]["steps"]
    owned = tmp_path / "k-csap-quality.83.2"
    sentinel = tmp_path / "other-job"
    sentinel.write_text("unchanged")
    if stale:
        owned.mkdir()
        (owned / "stale").write_text("untrusted")
    output = tmp_path / "output"
    env = {**os.environ, "RUN_ID": "83", "RUN_ATTEMPT": "2",
           "GITHUB_WORKSPACE": str(tmp_path), "GITHUB_OUTPUT": str(output)}
    prepared = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", steps[1]["run"]],
                              env=env, capture_output=True, text=True, check=False)
    assert prepared.returncode == (1 if stale else 0), prepared.stderr
    if stale:
        assert (owned / "stale").read_text() == "untrusted"
        source_path = ""
    else:
        assert output.read_text().strip() == "source_path=k-csap-quality.83.2"
        assert owned.is_dir()
        source_path = owned.name
    cleared = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", steps[-1]["run"]],
                             env={**env, "SOURCE_PATH": source_path},
                             capture_output=True, text=True, check=False)
    assert cleared.returncode == 0, cleared.stderr
    assert owned.exists() is stale
    assert sentinel.read_text() == "unchanged"


@pytest.mark.parametrize(
    ("event", "head", "ref", "state", "sha", "expected"),
    [
        ("push", "", "refs/heads/master", "open", "a" * 40, 0),
        ("push", "", "refs/heads/dev", "open", "a" * 40, 1),
        ("workflow_dispatch", "", "refs/tags/v1", "open", "a" * 40, 1),
        ("pull_request", "ContextualWisdomLab/k-csap-skills", "refs/pull/7/merge", "closed", "a" * 40, 1),
        ("pull_request", "ContextualWisdomLab/k-csap-skills", "refs/pull/7/merge", "open", "INVALID", 1),
    ],
)
def test_admission_rejects_non_master_closed_pr_and_invalid_sha(
    event, head, ref, state, sha, expected, tmp_path
):
    import os
    import subprocess

    script = workflow()["jobs"]["quality"]["steps"][0]["run"]
    env = {**os.environ, "TARGET_REPOSITORY": "ContextualWisdomLab/k-csap-skills",
           "EVENT_NAME": event, "HEAD_REPOSITORY": head, "EVENT_REF": ref,
           "PR_STATE": state, "EXPECTED_SHA": sha,
           "GITHUB_OUTPUT": str(tmp_path / "output")}
    proc = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                          env=env, capture_output=True, text=True, check=False)
    assert proc.returncode == expected, proc.stderr
