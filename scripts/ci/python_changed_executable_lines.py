"""Classify changed Python lines using coverage.py's executable statement map."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any

from coverage import Coverage
from coverage.parser import PythonParser


HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-c", f"safe.directory={repo_root.resolve()}", "-C", str(repo_root), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return completed.stdout


def changed_python_lines(
    repo_root: Path,
    base_sha: str,
    head_sha: str,
    project_dir: str = ".",
) -> dict[str, set[int]]:
    """Return added/modified physical lines for Python files in the exact diff."""
    names = _git(
        repo_root,
        "diff",
        "--name-status",
        "-z",
        "--find-renames",
        "--diff-filter=ACMR",
        base_sha,
        head_sha,
    )
    changed: dict[str, set[int]] = {}
    records = iter(names.split("\0"))
    for status in records:
        if not status:
            break
        old_path = next(records) if status.startswith("R") else None
        raw_path = next(records)
        path = PurePosixPath(raw_path)
        if path.suffix != ".py" or (
            project_dir != "."
            and not (path == PurePosixPath(project_dir) or path.is_relative_to(PurePosixPath(project_dir)))
        ):
            continue
        diff_paths = (old_path, raw_path) if old_path is not None else (raw_path,)
        diff = _git(
            repo_root,
            "diff",
            "--unified=0",
            "--no-color",
            "--find-renames",
            base_sha,
            head_sha,
            "--",
            *diff_paths,
        )
        lines: set[int] = set()
        for diff_line in diff.splitlines():
            match = HUNK_RE.match(diff_line)
            if match is None:
                continue
            start = int(match.group(1))
            count = int(match.group(2) or "1")
            lines.update(range(start, start + count))
        if lines:
            changed[raw_path] = lines
    return changed


def executable_lines(repo_root: Path, path: str) -> set[int]:
    """Return coverage.py statement-start lines, including excluded statements."""
    filename = (repo_root / Path(*PurePosixPath(path).parts)).resolve(strict=True)
    parser = PythonParser(text=filename.read_text(encoding="utf-8"), filename=str(filename))
    parser.parse_source()
    return set(parser.statements)


def statement_start_for_lines(repo_root: Path, path: str) -> dict[int, int]:
    """Map every physical line in a statement span to its statement start."""
    filename = (repo_root / Path(*PurePosixPath(path).parts)).resolve(strict=True)
    parser = PythonParser(text=filename.read_text(encoding="utf-8"), filename=str(filename))
    parser.parse_source()
    line_count = len(filename.read_text(encoding="utf-8").splitlines())
    return {line: parser.multiline_map.get(line, line) for line in range(1, line_count + 1)}


def measured_lines(repo_root: Path, path: str, data_file: Path) -> set[int]:
    """Return lines recorded as executed for one source file."""
    filename = (repo_root / Path(*PurePosixPath(path).parts)).resolve(strict=True)
    coverage = Coverage(data_file=str(data_file))
    coverage.load()
    measured = {Path(name).resolve(): name for name in coverage.get_data().measured_files()}
    recorded_name = measured.get(filename)
    if recorded_name is None:
        return set()
    return set(coverage.get_data().lines(recorded_name) or ())


def classify(
    repo_root: Path, base_sha: str, head_sha: str, project_dir: str = "."
) -> dict[str, Any]:
    """Return changed executable lines and the lines missing from measured data."""
    result: dict[str, Any] = {}
    for path, changed in changed_python_lines(repo_root, base_sha, head_sha, project_dir).items():
        executable = executable_lines(repo_root, path)
        starts = statement_start_for_lines(repo_root, path)
        result[path] = {
            "changed": sorted(changed),
            "executable": sorted({starts[line] for line in changed if line in starts} & executable),
        }
    return result


def evaluate(
    repo_root: Path,
    base_sha: str,
    head_sha: str,
    data_file: Path,
    project_dir: str = ".",
) -> dict[str, Any]:
    """Return executable changed lines and the subset absent from coverage data."""
    result: dict[str, Any] = {}
    for path, changed in changed_python_lines(repo_root, base_sha, head_sha, project_dir).items():
        starts = statement_start_for_lines(repo_root, path)
        executable = {starts[line] for line in changed if line in starts} & executable_lines(
            repo_root, path
        )
        covered = executable & measured_lines(repo_root, path, data_file)
        result[path] = {
            "changed": sorted(changed),
            "executable": sorted(executable),
            "covered": sorted(covered),
            "missing": sorted(executable - covered),
        }
    return result


def enforce(
    repo_root: Path,
    base_sha: str,
    head_sha: str,
    data_file: Path,
    minimum: float,
    project_dir: str = ".",
) -> tuple[dict[str, Any], bool]:
    """Evaluate changed executable coverage and return whether the threshold passes."""
    result = evaluate(repo_root, base_sha, head_sha, data_file, project_dir)
    executable = sum(len(entry["executable"]) for entry in result.values())
    covered = sum(len(entry["covered"]) for entry in result.values())
    percentage = 100.0 if executable == 0 else covered / executable * 100
    return (
        {
            "files": result,
            "covered": covered,
            "executable": executable,
            "percentage": round(percentage, 2),
            "minimum": minimum,
        },
        percentage >= minimum,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--coverage-data", type=Path)
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--minimum", type=float, default=90.0)
    args = parser.parse_args()
    if args.coverage_data is None:
        result = classify(args.repo_root, args.base_sha, args.head_sha, args.project_dir)
    else:
        result, passed = enforce(
            args.repo_root,
            args.base_sha,
            args.head_sha,
            args.coverage_data,
            args.minimum,
            args.project_dir,
        )
        print(json.dumps(result, sort_keys=True))
        return 0 if passed else 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
