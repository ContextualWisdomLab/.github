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
