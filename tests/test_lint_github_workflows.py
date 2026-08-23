"""Behavioral regressions for bounded actionlint and ShellCheck execution."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]
LINTER = ROOT / "scripts" / "ci" / "lint_github_workflows.rb"
AUTOFIX_WORKFLOW = ROOT / ".github" / "workflows" / "pr-review-autofix.yml"


def _write_executable(path: Path, source: str) -> None:
    """Write one executable test transport with deterministic behavior."""

    path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _tool_environment(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """Return isolated fake lint executables and their capture directory."""

    binary_dir = tmp_path / "bin"
    capture_dir = tmp_path / "captures"
    binary_dir.mkdir()
    capture_dir.mkdir()
    _write_executable(
        binary_dir / "actionlint",
        """
        #!/usr/bin/env python3
        import json
        import os
        from pathlib import Path
        import sys

        capture = Path(os.environ["LINT_CAPTURE_DIR"]) / "actionlint.json"
        capture.write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
        print(os.environ.get("ACTIONLINT_OUTPUT", ""), end="")
        raise SystemExit(int(os.environ.get("ACTIONLINT_STATUS", "0")))
        """,
    )
    _write_executable(
        binary_dir / "shellcheck",
        """
        #!/usr/bin/env python3
        import json
        import os
        from pathlib import Path
        import sys

        root = Path(os.environ["LINT_CAPTURE_DIR"])
        index = len(list(root.glob("shellcheck-*.json")))
        script = Path(sys.argv[-1]).read_text(encoding="utf-8")
        (root / f"shellcheck-{index}.json").write_text(
            json.dumps({"args": sys.argv[1:], "script": script}),
            encoding="utf-8",
        )
        if "FINDING_MARKER" in script:
            print(json.dumps([{
                "line": 3,
                "column": 7,
                "level": "warning",
                "code": 2086,
                "message": "Double quote to prevent globbing.",
            }]))
            raise SystemExit(1)
        if os.environ.get("SHELLCHECK_MALFORMED") == "1":
            print("not-json")
            raise SystemExit(0)
        print("[]")
        """,
    )
    environment = {
        **os.environ,
        "PATH": f"{binary_dir}{os.pathsep}{os.environ['PATH']}",
        "ACTIONLINT": str(binary_dir / "actionlint"),
        "SHELLCHECK": str(binary_dir / "shellcheck"),
        "LINT_CAPTURE_DIR": str(capture_dir),
    }
    return environment, capture_dir


def _run_linter(workflow: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the real trusted linter against one controlled workflow."""

    return subprocess.run(
        ["ruby", str(LINTER), str(workflow)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_linter_uses_actionlint_schema_and_file_based_shellcheck(tmp_path: Path) -> None:
    """Large Bash and explicit sh scripts use files while other shells stay excluded."""

    environment, capture_dir = _tool_environment(tmp_path)
    workflow = tmp_path / "large.yml"
    large_body = "\n".join("          # bounded filler" for _ in range(4_000))
    workflow.write_text(
        "\n".join(
            (
                "name: large-shell-boundary",
                "on: push",
                "defaults:",
                "  run:",
                "    shell: bash",
                "concurrency:",
                "  group: exact",
                "  queue: max",
                "jobs:",
                "  linux:",
                "    runs-on: ubuntu-24.04",
                "    steps:",
                "      - name: Large Bash",
                "        run: |",
                '          echo "${{ github.sha }}"',
                large_body,
                "      - name: Explicit sh",
                "        shell: sh",
                "        run: echo ok",
                "      - name: Python",
                "        shell: python",
                "        run: print('ok')",
                "  windows:",
                "    runs-on: windows-2025",
                "    steps:",
                "      - shell: pwsh",
                "        run: Write-Host ok",
                "",
            )
        ),
        encoding="utf-8",
    )

    result = _run_linter(workflow, environment)

    actionlint_args = json.loads(
        (capture_dir / "actionlint.json").read_text(encoding="utf-8")
    )
    shellcheck_records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(capture_dir.glob("shellcheck-*.json"))
    ]
    assert result.returncode == 0, result.stderr
    assert actionlint_args[0] == "-shellcheck="
    assert actionlint_args[-1] == str(workflow)
    assert len(shellcheck_records) == 2
    assert shellcheck_records[0]["args"][:7] == [
        "--norc",
        "-f",
        "json",
        "-x",
        "--shell",
        "bash",
        "-e",
    ]
    assert shellcheck_records[0]["args"][-1] != "-"
    assert shellcheck_records[0]["script"].startswith(
        'set -eo pipefail\necho "_________________"\n'
    )
    assert len(shellcheck_records[0]["script"].encode()) > 65_536
    assert shellcheck_records[1]["args"][5] == "sh"
    assert shellcheck_records[1]["script"] == "set -e\necho ok\n"


def test_write_capable_autofix_always_uses_the_trusted_linter() -> None:
    """Changed workflows fail closed through the dispatch-pinned helper."""

    workflow = AUTOFIX_WORKFLOW.read_text(encoding="utf-8")
    invocation = (
        'ruby "$GITHUB_WORKSPACE/trusted-autofix-source/scripts/ci/'
        'lint_github_workflows.rb"'
    )

    assert invocation in workflow
    assert "command -v actionlint" not in workflow


def test_linter_reports_shellcheck_findings_with_workflow_context(tmp_path: Path) -> None:
    """A delegated finding remains actionable without exposing a temporary filename."""

    environment, _capture_dir = _tool_environment(tmp_path)
    workflow = tmp_path / "finding.yml"
    workflow.write_text(
        """name: finding
on: push
jobs:
  verify:
    runs-on: ubuntu-24.04
    steps:
      - name: Unsafe expansion
        run: |
          echo FINDING_MARKER
""",
        encoding="utf-8",
    )

    result = _run_linter(workflow, environment)

    assert result.returncode == 1
    assert str(workflow) in result.stderr
    assert "job=verify" in result.stderr
    assert "step=Unsafe expansion" in result.stderr
    assert "SC2086:warning:2:7" in result.stderr
    assert "Double quote to prevent globbing" in result.stderr


def test_linter_rejects_unsupported_queue_before_actionlint(tmp_path: Path) -> None:
    """The temporary actionlint exception cannot admit an invented queue value."""

    environment, capture_dir = _tool_environment(tmp_path)
    workflow = tmp_path / "bad-queue.yml"
    workflow.write_text(
        """name: bad-queue
on: push
concurrency:
  group: exact
  queue: newest
jobs: {}
""",
        encoding="utf-8",
    )

    result = _run_linter(workflow, environment)

    assert result.returncode == 2
    assert "queue must be exactly max" in result.stderr
    assert not (capture_dir / "actionlint.json").exists()


@pytest.mark.parametrize(
    ("environment_update", "expected"),
    (
        ({"ACTIONLINT_STATUS": "3", "ACTIONLINT_OUTPUT": "schema failure\n"}, "schema failure"),
        ({"SHELLCHECK_MALFORMED": "1"}, "invalid ShellCheck JSON"),
    ),
)
def test_linter_fails_closed_on_tool_failures(
    tmp_path: Path,
    environment_update: dict[str, str],
    expected: str,
) -> None:
    """Schema-process and result-integrity failures never become clean evidence."""

    environment, _capture_dir = _tool_environment(tmp_path)
    environment.update(environment_update)
    workflow = tmp_path / "tool-failure.yml"
    workflow.write_text(
        """name: tool-failure
on: push
jobs:
  verify:
    runs-on: ubuntu-24.04
    steps:
      - run: echo ok
""",
        encoding="utf-8",
    )

    result = _run_linter(workflow, environment)

    assert result.returncode != 0
    assert expected in result.stderr
