import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _extract_run_block(workflow_text: str, step_name: str) -> str:
    lines = workflow_text.splitlines()
    step_index = next(
        index for index, line in enumerate(lines) if line.strip() == f"- name: {step_name}"
    )
    run_index = next(
        index
        for index in range(step_index + 1, len(lines))
        if lines[index].strip() == "run: |"
    )
    run_indent = len(lines[run_index]) - len(lines[run_index].lstrip())
    block_lines = []
    for line in lines[run_index + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= run_indent:
            break
        block_lines.append(line[run_indent + 2 :] if len(line) >= run_indent + 2 else "")
    return "\n".join(block_lines) + "\n"


def test_opencode_review_run_blocks_are_valid_bash():
    workflow_text = (REPO_ROOT / ".github/workflows/opencode-review-dispatch.yml").read_text(
        encoding="utf-8"
    )
    assert 'gsub("`"; "&apos;")' in workflow_text
    assert 'gsub("`"; "\'")' not in workflow_text

    if sys.platform == "win32":
        return
    bash = shutil.which("bash")
    if bash is None:
        return

    for step_name in (
        "Materialize pull request merge tree for coverage measurement",
        "Prepare bounded OpenCode review evidence",
        "Enforce changed-file syntax gate",
        "Publish bounded OpenCode review comment",
        "Publish OpenCode review outcome",
        "Run merge scheduler after approval",
    ):
        script = _extract_run_block(workflow_text, step_name)
        result = subprocess.run(
            [bash, "-n"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, f"{step_name}: {result.stderr}"


def test_opencode_review_comment_helpers_are_shared_and_valid_bash():
    workflow_text = (REPO_ROOT / ".github/workflows/opencode-review-dispatch.yml").read_text(
        encoding="utf-8"
    )
    helper_path = REPO_ROOT / "scripts/ci/opencode_review_comment_helpers.sh"
    helper_text = helper_path.read_text(encoding="utf-8")

    assert workflow_text.count(
        ". scripts/ci/opencode_review_comment_helpers.sh"
    ) == 2
    for function_name in (
        "emit_change_flow_mermaid_graph",
        "append_mermaid_review_graph",
        "ensure_review_body_has_change_graph",
        "append_merge_conflict_guidance",
    ):
        assert f"{function_name}() {{" not in workflow_text
        assert f"{function_name}() {{" in helper_text

    if sys.platform == "win32":
        return
    bash = shutil.which("bash")
    if bash is None:
        return
    result = subprocess.run(
        [bash, "-n", str(helper_path)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_merge_scheduler_review_followup_run_block_is_valid_bash():
    """The App-review follow-up keeps its dynamic wait logic valid Bash."""
    if sys.platform == "win32":
        return
    bash = shutil.which("bash")
    if bash is None:
        return

    workflow_text = (
        REPO_ROOT / ".github/workflows/pr-review-merge-scheduler.yml"
    ).read_text(encoding="utf-8")
    script = _extract_run_block(
        workflow_text,
        "Wait for approved OpenCode publication run to finish",
    )
    result = subprocess.run(
        [bash, "-n"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_merge_scheduler_targeted_dispatch_run_block_is_valid_bash():
    """The exact-target allowlist and live-PR validation stays valid Bash."""
    if sys.platform == "win32":
        return
    bash = shutil.which("bash")
    if bash is None:
        return

    workflow_text = (
        REPO_ROOT / ".github/workflows/pr-review-merge-scheduler.yml"
    ).read_text(encoding="utf-8")
    script = _extract_run_block(
        workflow_text,
        "Validate targeted repository dispatch",
    )
    result = subprocess.run(
        [bash, "-n"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_merge_scheduler_targeted_dispatch_validates_live_exact_pr(tmp_path):
    """Allowlisted open PRs keep exact outputs even when their head is a fork."""
    if sys.platform == "win32":
        return
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    if bash is None or jq is None:
        return

    workflow_text = (
        REPO_ROOT / ".github/workflows/pr-review-merge-scheduler.yml"
    ).read_text(encoding="utf-8")
    script = _extract_run_block(
        workflow_text,
        "Validate targeted repository dispatch",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
test "$1" = api
case "$2" in
  repos/ContextualWisdomLab/naruon/pulls/1179)
    printf '%s\\n' "$FAKE_PULL_JSON"
    ;;
  repos/ContextualWisdomLab/naruon)
    printf '%s\\n' 'main'
    ;;
  *)
    exit 1
    ;;
esac
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    pull = {
        "number": 1179,
        "state": "open",
        "base": {
            "ref": "develop",
            "repo": {"full_name": "ContextualWisdomLab/naruon"},
        },
        "head": {
            "sha": "4afd4af7ad343660356791873d940aa2846f40c2",
            "repo": {"full_name": "ContextualWisdomLab/naruon"},
        },
    }
    output = tmp_path / "github-output"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_PULL_JSON": json.dumps(pull),
        "GITHUB_EVENT_NAME": "repository_dispatch",
        "GITHUB_REPOSITORY": "ContextualWisdomLab/.github",
        "GITHUB_OUTPUT": str(output),
        "DEFAULT_BRANCH": "main",
        "TARGET_REPOSITORY_INPUT": "ContextualWisdomLab/naruon",
        "TARGET_PR_NUMBER": "1179",
        "TARGET_BASE_BRANCH_INPUT": "develop",
        "ALLOWED_TARGET_REPOSITORIES": (
            "ContextualWisdomLab/.github, ContextualWisdomLab/naruon"
        ),
    }

    accepted = subprocess.run(
        [bash],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert accepted.returncode == 0, accepted.stderr
    assert output.read_text(encoding="utf-8").splitlines() == [
        "repository=ContextualWisdomLab/naruon",
        "base_branch=main",
        "head_sha=4afd4af7ad343660356791873d940aa2846f40c2",
    ]

    output.unlink()
    rejected_env = {
        **env,
        "ALLOWED_TARGET_REPOSITORIES": "ContextualWisdomLab/.github",
    }
    rejected = subprocess.run(
        [bash],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env=rejected_env,
    )

    assert rejected.returncode == 1
    assert "absent from the configured exact allowlist" in rejected.stdout
    assert not output.exists()

    output.unlink(missing_ok=True)
    cross_repo_pull = {
        **pull,
        "head": {
            **pull["head"],
            "repo": {"full_name": "outside/fork"},
        },
    }
    cross_repo_env = {
        **env,
        "FAKE_PULL_JSON": json.dumps(cross_repo_pull),
    }
    cross_repo = subprocess.run(
        [bash],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env=cross_repo_env,
    )

    assert cross_repo.returncode == 0, cross_repo.stderr
    assert output.read_text(encoding="utf-8").splitlines() == [
        "repository=ContextualWisdomLab/naruon",
        "base_branch=main",
        "head_sha=4afd4af7ad343660356791873d940aa2846f40c2",
    ]

    output.unlink()
    malformed_head_env = {
        **env,
        "FAKE_PULL_JSON": json.dumps(
            {
                **cross_repo_pull,
                "head": {
                    **cross_repo_pull["head"],
                    "repo": {"full_name": "outside/fork/extra"},
                },
            }
        ),
    }
    malformed_head = subprocess.run(
        [bash],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env=malformed_head_env,
    )

    assert malformed_head.returncode == 1
    assert "malformed live PR metadata" in malformed_head.stdout
    assert not output.exists()


def _run_noema_validate_head(tmp_path, *, live_state: str, live_head_sha: str, expected_head_sha: str):
    """Execute noema-review.yml's ``Validate current pull request head`` step."""
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    assert bash is not None and jq is not None

    workflow_text = (REPO_ROOT / ".github/workflows/noema-review.yml").read_text(
        encoding="utf-8"
    )
    script = _extract_run_block(workflow_text, "Validate current pull request head")

    fake_bin = tmp_path / f"bin-{live_state}-{live_head_sha}-{expected_head_sha}"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
test "$1" = api
printf '%s\\n' "$FAKE_PULL_JSON"
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    pull = {"state": live_state, "head": {"sha": live_head_sha}}
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_PULL_JSON": json.dumps(pull),
        "TARGET_REPOSITORY": "ContextualWisdomLab/newsdom-api",
        "PR_NUMBER": "1",
        "EXPECTED_HEAD_SHA": expected_head_sha,
    }
    return subprocess.run(
        [bash], input=script, text=True, capture_output=True, check=False, env=env
    )


def test_noema_validate_head_distinguishes_closed_from_stale(tmp_path):
    """A closed PR on its current head is not the same failure as a stale head.

    Regression test: an async Noema review job that finishes after
    the target PR was merged/closed through another path (e.g. the merge
    scheduler) must skip cleanly, not report a spurious job failure. A PR
    whose head actually moved past what this job was reviewing must still
    fail loudly.
    """
    if sys.platform == "win32":
        return
    if shutil.which("bash") is None or shutil.which("jq") is None:
        return

    head = "a" * 40
    other_head = "b" * 40

    open_current = _run_noema_validate_head(
        tmp_path, live_state="open", live_head_sha=head, expected_head_sha=head
    )
    assert open_current.returncode == 0
    assert "::error::" not in open_current.stdout
    assert "::notice::" not in open_current.stdout

    closed_current = _run_noema_validate_head(
        tmp_path, live_state="closed", live_head_sha=head, expected_head_sha=head
    )
    assert closed_current.returncode == 0, closed_current.stderr
    assert "::error::" not in closed_current.stdout
    assert "nothing left to review" in closed_current.stdout

    genuinely_stale = _run_noema_validate_head(
        tmp_path, live_state="open", live_head_sha=other_head, expected_head_sha=head
    )
    assert genuinely_stale.returncode == 1
    assert "review target is stale" in genuinely_stale.stdout

    closed_and_stale = _run_noema_validate_head(
        tmp_path, live_state="closed", live_head_sha=other_head, expected_head_sha=head
    )
    assert closed_and_stale.returncode == 1
    assert "review target is stale" in closed_and_stale.stdout
