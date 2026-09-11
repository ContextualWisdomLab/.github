"""Regression tests for changed Python executable-line classification."""

from pathlib import Path
import subprocess

from scripts.ci.python_changed_executable_lines import classify, executable_lines
from scripts.ci.python_changed_executable_lines import enforce, evaluate


def _commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True, stdout=subprocess.PIPE)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


def _fixture(tmp_path: Path, source: str) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    path = repo / "module.py"
    path.write_text(source)
    base = _commit(repo, "base")
    return repo, base, str(path)


def test_docstring_only_change_has_no_executable_changed_lines(tmp_path: Path) -> None:
    repo, base, path = _fixture(
        tmp_path,
        'def public(value):\n    """Original reference."""\n    return value\n',
    )
    Path(path).write_text(
        'def public(value):\n    """Updated reference with more detail.\n\n    Source note.\n    """\n    return value\n'
    )
    head = _commit(repo, "docs")
    result = classify(repo, base, head)
    assert result["module.py"]["executable"] == []


def test_mixed_change_keeps_only_executable_statement(tmp_path: Path) -> None:
    repo, base, path = _fixture(
        tmp_path,
        'def public(value):\n    """Original reference."""\n    return value\n',
    )
    Path(path).write_text(
        'def public(value):\n    """Updated reference."""\n    result = value + 1\n    return result\n'
    )
    head = _commit(repo, "docs and code")
    result = classify(repo, base, head)
    assert result["module.py"]["executable"] == [3, 4]


def test_multiline_condition_maps_to_statement_start(tmp_path: Path) -> None:
    repo, _base, path = _fixture(
        tmp_path,
        'def public(value):\n    if (\n        value\n    ):\n        return 1\n    return 0\n',
    )
    assert executable_lines(repo, "module.py") == {1, 2, 5, 6}


def test_uncovered_changed_statement_remains_missing(tmp_path: Path) -> None:
    repo, base, path = _fixture(
        tmp_path,
        'def public(value):\n    return value\n',
    )
    Path(path).write_text(
        'def public(value):\n    if value:\n        return 1\n    return 0\n'
    )
    head = _commit(repo, "add branch")
    subprocess.run(
        ["python", "-m", "coverage", "run", "--data-file", str(repo / ".coverage"), path],
        cwd=repo,
        check=True,
    )
    result = evaluate(repo, base, head, repo / ".coverage")
    assert result["module.py"]["executable"] == [2, 3, 4]
    assert result["module.py"]["missing"] == [2, 3, 4]


def test_threshold_is_not_lowered_for_real_changed_code(tmp_path: Path) -> None:
    repo, base, path = _fixture(
        tmp_path,
        'def public(value):\n    return value\n',
    )
    Path(path).write_text(
        'def public(value):\n    if value:\n        return 1\n    return 0\n'
    )
    head = _commit(repo, "add branch")
    subprocess.run(
        ["python", "-m", "coverage", "run", "--data-file", str(repo / ".coverage"), path],
        cwd=repo,
        check=True,
    )
    result, passed = enforce(repo, base, head, repo / ".coverage", 90.0)
    assert result["executable"] == 3
    assert result["covered"] == 0
    assert not passed
