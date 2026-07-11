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
    workflow_text = (REPO_ROOT / ".github/workflows/opencode-review.yml").read_text(
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
        "Prepare bounded OpenCode review evidence",
        "Approve PR if OpenCode review passed",
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
