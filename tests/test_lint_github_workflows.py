"""Behavioral regressions for bounded actionlint and shfmt execution."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
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
        binary_dir / "shfmt",
        """
        #!/usr/bin/env python3
        import json
        import os
        from pathlib import Path
        import sys

        root = Path(os.environ["LINT_CAPTURE_DIR"])
        index = len(list(root.glob("shfmt-*.json")))
        script = sys.stdin.read()
        (root / f"shfmt-{index}.json").write_text(
            json.dumps({"args": sys.argv[1:], "script": script}),
            encoding="utf-8",
        )
        if "SYNTAX_ERROR_MARKER" in script:
            print("standard input:2:7: expected command", file=sys.stderr)
            raise SystemExit(3)
        if os.environ.get("SHFMT_MALFORMED") == "1":
            print("not-json")
            raise SystemExit(0)
        print("{}")
        """,
    )
    environment = {
        **os.environ,
        "PATH": f"{binary_dir}{os.pathsep}{os.environ['PATH']}",
        "LINT_CAPTURE_DIR": str(capture_dir),
    }
    return environment, capture_dir


def _run_linter(workflow: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the real trusted linter against one controlled workflow."""

    if shutil.which("ruby", path=environment["PATH"]) is None:
        pytest.skip("Ruby is unavailable; the hosted quality job runs this runtime contract")
    return subprocess.run(
        ["ruby", str(LINTER), str(workflow)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_linter_uses_actionlint_schema_and_bounded_shfmt_parser(tmp_path: Path) -> None:
    """Large Bash and explicit sh scripts reach shfmt without content loss."""

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
                "  cancel-in-progress: false",
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
    shfmt_records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(capture_dir.glob("shfmt-*.json"))
    ]
    assert result.returncode == 0, result.stderr
    assert actionlint_args[0] == "-shellcheck="
    assert actionlint_args[-1] == str(workflow)
    assert len(shfmt_records) == 2
    assert shfmt_records[0]["args"] == ["-ln", "bash", "-tojson"]
    assert shfmt_records[0]["script"].startswith(
        'set -eo pipefail\necho "_________________"\n'
    )
    assert len(shfmt_records[0]["script"].encode()) > 65_536
    assert shfmt_records[1]["args"] == ["-ln", "posix", "-tojson"]
    assert shfmt_records[1]["script"] == "set -e\necho ok\n"


def test_linter_preserves_lines_inside_multiline_expressions(tmp_path: Path) -> None:
    """Expression sanitizing keeps shfmt source and diagnostic lines aligned."""

    environment, capture_dir = _tool_environment(tmp_path)
    workflow = tmp_path / "multiline-expression.yml"
    workflow.write_text(
        """name: multiline-expression
on: push
jobs:
  verify:
    runs-on: ubuntu-24.04
    steps:
      - run: |
          echo "${{
            github.sha
          }}"
          echo after
""",
        encoding="utf-8",
    )

    result = _run_linter(workflow, environment)

    record = json.loads(
        (capture_dir / "shfmt-0.json").read_text(encoding="utf-8")
    )
    lines = record["script"].splitlines()
    assert result.returncode == 0, result.stderr
    assert lines[2].strip(" _") == ""
    assert lines[3].endswith('"')
    assert lines[4] == "echo after"


def test_write_capable_autofix_always_uses_the_trusted_linter() -> None:
    """Changed workflows use checksum-pinned tools and the trusted helper."""

    workflow = AUTOFIX_WORKFLOW.read_text(encoding="utf-8")
    invocation = (
        'ruby "$GITHUB_WORKSPACE/trusted-autofix-source/scripts/ci/'
        'lint_github_workflows.rb"'
    )

    assert invocation in workflow
    assert "command -v actionlint" not in workflow
    assert "actionlint_1.7.12_linux_amd64.tar.gz" in workflow
    assert (
        "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8"
        in workflow
    )
    assert (
        'tar -xzf "$actionlint_archive" -C "$RUNNER_TEMP" actionlint'
        in workflow
    )
    assert 'PATH="${RUNNER_TEMP}:${PATH}"' in workflow


def test_linter_invokes_fixed_tool_names_without_dynamic_command_selection() -> None:
    """Repository input cannot select the executable passed to Open3."""

    source = LINTER.read_text(encoding="utf-8")

    assert 'ENV.fetch("ACTIONLINT"' not in source
    assert 'ENV.fetch("SHFMT"' not in source
    assert 'Open3.capture3("actionlint", *arguments)' in source
    assert 'Open3.capture3("shfmt", "-ln", "bash", "-tojson"' in source
    assert 'Open3.capture3("shfmt", "-ln", "posix", "-tojson"' in source
    assert "findings = workflows.sum" not in source
    assert source.count(
        "# nosemgrep: ruby.lang.security.dangerous-exec.dangerous-exec"
    ) == 1


def test_linter_uses_permissive_pinned_shfmt_instead_of_shellcheck() -> None:
    """The write-capable linter must not add a GPL tool dependency."""

    source = LINTER.read_text(encoding="utf-8")
    workflow = AUTOFIX_WORKFLOW.read_text(encoding="utf-8")

    assert 'Open3.capture3("shfmt",' in source
    assert 'Open3.capture3("shellcheck",' not in source
    assert "shfmt_v3.13.1_linux_amd64" in workflow
    assert "fb096c5d1ac6beabbdbaa2874d025badb03ee07929f0c9ff67563ce8c75398b1" in workflow


def test_linter_reports_shfmt_syntax_failures_with_workflow_context(tmp_path: Path) -> None:
    """A parser failure identifies the governed workflow job and step."""

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
          echo SYNTAX_ERROR_MARKER
""",
        encoding="utf-8",
    )

    result = _run_linter(workflow, environment)

    assert result.returncode == 2
    assert str(workflow) in result.stderr
    assert "job=verify" in result.stderr
    assert "step=Unsafe expansion" in result.stderr
    assert "standard input:2:7: expected command" in result.stderr


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
    "workflow_source",
    (
        """name: cancelled-workflow-queue
on: push
concurrency:
  group: exact
  queue: max
  cancel-in-progress: true
jobs: {}
""",
        """name: cancelled-job-queue
on: push
jobs:
  verify:
    runs-on: ubuntu-24.04
    concurrency:
      group: exact
      queue: max
      cancel-in-progress: true
    steps: []
""",
    ),
)
def test_linter_rejects_queue_max_with_static_cancellation(
    tmp_path: Path,
    workflow_source: str,
) -> None:
    """GitHub permits an expanded queue only when cancellation is disabled."""

    environment, capture_dir = _tool_environment(tmp_path)
    workflow = tmp_path / "cancelled-queue.yml"
    workflow.write_text(workflow_source, encoding="utf-8")

    result = _run_linter(workflow, environment)

    assert result.returncode == 2
    assert "queue max requires cancel-in-progress to be false or absent" in result.stderr
    assert not (capture_dir / "actionlint.json").exists()


@pytest.mark.parametrize(
    ("environment_update", "expected"),
    (
        ({"ACTIONLINT_STATUS": "3", "ACTIONLINT_OUTPUT": "schema failure\n"}, "schema failure"),
        ({"SHFMT_MALFORMED": "1"}, "invalid shfmt JSON"),
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
