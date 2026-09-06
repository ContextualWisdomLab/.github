"""Regression coverage for the `find | head -1 | grep -q .` SIGPIPE race.

Under `set -o pipefail`, `find ... | head -1 | grep -q .` races: if `find`
still has buffered matches to write when `head -1` reads its one line and
closes its end of the pipe, the next `write()` inside `find` fails with
SIGPIPE and `find` exits non-zero. `head`/`grep` still exit zero, but
`pipefail` reports the pipeline's exit status as the last non-zero one in
pipeline order, which is `find`'s -- so the surrounding `if` silently
evaluates false even though a match existed, whenever there is enough
matching output to overflow the pipe buffer before `head` closes it (readily
reproducible with a few thousand matches). `find ... -print -quit` avoids
this entirely: `find` stops itself after the first match (or none), so
nothing external ever cuts off its output. This is this repository's own
established idiom for the same check -- see
`test_opencode_agent_contract.py`'s `find "$destination" -type l -print
-quit`.
"""

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

_AFFECTED_WORKFLOWS = (
    "codeql-pr.yml",
    "python-security.yml",
    "scheduled-security-scan.yml",
)


def test_no_affected_workflow_uses_the_pipefail_prone_find_head_grep_idiom():
    for filename in _AFFECTED_WORKFLOWS:
        workflow = (REPO_ROOT / ".github/workflows" / filename).read_text(
            encoding="utf-8"
        )
        assert "head -1 | grep -q" not in workflow, filename
        assert "-print -quit | grep -q ." in workflow, filename


def test_codeql_pr_language_matrix_uses_print_quit_for_all_three_languages():
    workflow = (REPO_ROOT / ".github/workflows/codeql-pr.yml").read_text(
        encoding="utf-8"
    )
    assert workflow.count("-print -quit | grep -q .") == 3


def test_scheduled_security_scan_language_matrix_uses_print_quit():
    workflow = (REPO_ROOT / ".github/workflows/scheduled-security-scan.yml").read_text(
        encoding="utf-8"
    )
    assert workflow.count("-print -quit | grep -q .") == 2


def test_python_security_detection_uses_print_quit_for_python_manifest_and_project():
    workflow = (REPO_ROOT / ".github/workflows/python-security.yml").read_text(
        encoding="utf-8"
    )
    assert workflow.count("-print -quit | grep -q .") == 2


def _extract_detect_python_script(workflow_text: str) -> str:
    marker = "      - name: Detect Python sources and dependency manifests\n"
    start = workflow_text.index(marker)
    run_start = workflow_text.index("        run: |\n", start) + len(
        "        run: |\n"
    )
    run_end = workflow_text.index("\n\n  bandit:", run_start)
    block = workflow_text[run_start:run_end]
    return "\n".join(line[10:] for line in block.splitlines())


def _run_detect_python(repo_dir: Path, output_file: Path, script: str) -> str:
    """Run the extracted step body with a real $GITHUB_OUTPUT target (the
    script runs under `set -u`, so this must be set) and return that file's
    contents -- exactly what the real GitHub Actions runner would read to
    populate `steps.detect.outputs.*`."""
    output_file.write_text("", encoding="utf-8")
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "GITHUB_OUTPUT": str(output_file)},
    )
    assert result.returncode == 0, result.stderr
    return output_file.read_text(encoding="utf-8")


def test_detect_python_step_survives_thousands_of_matching_files(tmp_path):
    """Extracts the real, current step body from python-security.yml (not a
    hand-copied duplicate, so this fails if the workflow regresses to the
    buggy idiom) and runs it against a directory with enough .py files and
    enough requirements*.txt files to overflow the pipe buffer before `head
    -1` would have closed it under the old idiom."""
    workflow = (REPO_ROOT / ".github/workflows/python-security.yml").read_text(
        encoding="utf-8"
    )
    script = _extract_detect_python_script(workflow)
    assert "find . -type f -name '*.py'" in script
    assert "has_python=${has_python}" in script

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    for index in range(5000):
        (repo_dir / f"module_{index}.py").write_text("", encoding="utf-8")
    for index in range(5000):
        (repo_dir / f"requirements-extra-{index}.txt").write_text(
            "", encoding="utf-8"
        )
    (repo_dir / "requirements.txt").write_text("", encoding="utf-8")

    outputs = _run_detect_python(repo_dir, tmp_path / "github_output.txt", script)

    assert "has_python=true" in outputs
    assert "has_manifest=true" in outputs


def test_detect_python_step_reports_false_when_nothing_matches(tmp_path):
    workflow = (REPO_ROOT / ".github/workflows/python-security.yml").read_text(
        encoding="utf-8"
    )
    script = _extract_detect_python_script(workflow)

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text("no python here", encoding="utf-8")

    outputs = _run_detect_python(repo_dir, tmp_path / "github_output.txt", script)

    assert "has_python=false" in outputs
    assert "has_manifest=false" in outputs
