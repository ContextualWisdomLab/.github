"""Runtime contract for Strix repository visibility routing."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github/workflows/strix.yml"


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
    block_lines: list[str] = []
    for line in lines[run_index + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= run_indent:
            break
        block_lines.append(line[run_indent + 2 :] if len(line) >= run_indent + 2 else "")
    return "\n".join(block_lines) + "\n"


def _run_visibility_step(
    tmp_path: Path,
    event_visibility: str,
    *,
    api_visibility: str = "",
) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required for the extracted workflow regression")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh_log = tmp_path / "gh-log"
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$FAKE_GH_LOG"
test "$1" = api
case "$*" in
  *visibility*) ;;
  *) echo "visibility query required" >&2; exit 64 ;;
esac
case "$FAKE_REPOSITORY_VISIBILITY" in
  public) printf 'false\\n' ;;
  private | internal) printf 'true\\n' ;;
  *) printf '\\n' ;;
esac
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    fake_sleep = fake_bin / "sleep"
    fake_sleep.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_sleep.chmod(0o755)

    output = tmp_path / "github-output"
    script = _extract_run_block(
        WORKFLOW.read_text(encoding="utf-8"),
        "Resolve target repository visibility",
    )
    return subprocess.run(
        [bash],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "TARGET_REPOSITORY": "ContextualWisdomLab/consumer",
            "EVENT_REPOSITORY_VISIBILITY": event_visibility,
            "FAKE_REPOSITORY_VISIBILITY": api_visibility,
            "FAKE_GH_LOG": str(gh_log),
            "GITHUB_OUTPUT": str(output),
        },
    )


@pytest.mark.parametrize(
    ("event_visibility", "expected_private"),
    [
        ("PUBLIC", "false"),
        ("public", "false"),
        ("PRIVATE", "true"),
        ("private", "true"),
        ("INTERNAL", "true"),
        ("internal", "true"),
    ],
)
def test_event_visibility_routes_without_api(
    tmp_path: Path,
    event_visibility: str,
    expected_private: str,
) -> None:
    result = _run_visibility_step(tmp_path, event_visibility)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "github-output").read_text(encoding="utf-8") == (
        f"is_private={expected_private}\n"
    )
    assert not (tmp_path / "gh-log").exists()


@pytest.mark.parametrize(
    ("api_visibility", "expected_private"),
    [("public", "false"), ("private", "true"), ("internal", "true")],
)
def test_dispatch_api_visibility_preserves_internal_privacy(
    tmp_path: Path,
    api_visibility: str,
    expected_private: str,
) -> None:
    result = _run_visibility_step(
        tmp_path,
        "",
        api_visibility=api_visibility,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "github-output").read_text(encoding="utf-8") == (
        f"is_private={expected_private}\n"
    )
    gh_invocation = (tmp_path / "gh-log").read_text(encoding="utf-8")
    assert ".visibility" in gh_invocation
    assert ".private" not in gh_invocation


@pytest.mark.parametrize("event_visibility", ["unknown", "archived"])
def test_unknown_event_visibility_fails_closed(
    tmp_path: Path,
    event_visibility: str,
) -> None:
    result = _run_visibility_step(tmp_path, event_visibility)

    assert result.returncode != 0
    assert "was not public, private, or internal" in result.stdout
    assert not (tmp_path / "github-output").exists()
    assert not (tmp_path / "gh-log").exists()


def test_unknown_dispatch_api_visibility_fails_closed(tmp_path: Path) -> None:
    result = _run_visibility_step(tmp_path, "", api_visibility="unknown")

    assert result.returncode != 0
    assert "did not resolve to true or false" in result.stdout
    assert not (tmp_path / "github-output").exists()
