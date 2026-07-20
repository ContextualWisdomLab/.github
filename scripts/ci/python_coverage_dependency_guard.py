"""Classify networkless pytest collection failures against trusted base metadata.

The central coverage sandbox deliberately does not resolve pull-request-selected
Python dependency manifests.  A repository test suite can therefore stop at
collection time when a dependency that is already declared on the protected
base branch is absent from the small central tool image.  This helper permits
that one state to be reported as deferred to repository-native required checks.
All undeclared imports and every non-collection test failure remain blocking.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import tomllib


SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
MISSING_MODULE_RE = re.compile(
    r"(?m)^E\s+ModuleNotFoundError:\s+No module named ['\"]([A-Za-z0-9_.-]+)['\"]\s*$"
)
TERMINAL_EXCEPTION_RE = re.compile(
    r"(?m)^E\s+([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Exit|Interrupt)):\s*"
)
REQUIREMENT_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")
MAX_LOG_BYTES = 10 * 1024 * 1024

# Import roots and distribution names are not always identical.  Keep this
# intentionally small and explicit; an unknown mapping stays fail-closed.
IMPORT_DISTRIBUTION_ALIASES = {
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "dateutil": "python-dateutil",
    "jwt": "pyjwt",
    "pil": "pillow",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
}


def normalize_distribution(name: str) -> str:
    """Return a PEP 503-style normalized distribution name."""
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def validate_project_dir(value: str) -> str:
    """Return a safe repository-relative project directory."""
    if value in {"", "."}:
        return "."
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("project directory must be a safe repository-relative path")
    return path.as_posix()


def git_show(repo_root: Path, base_sha: str, relative_path: str) -> str | None:
    """Read one file from the validated base commit without invoking hooks."""
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "-c",
            f"safe.directory={repo_root}",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "show",
            f"{base_sha}:{relative_path}",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env={
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": tempfile.gettempdir(),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
        },
    )
    if completed.returncode != 0:
        return None
    return completed.stdout


def requirement_names(text: str) -> set[str]:
    """Extract direct distribution names from a requirements-style file."""
    names: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        match = REQUIREMENT_NAME_RE.match(line)
        if match:
            names.add(normalize_distribution(match.group(1)))
    return names


def pyproject_names(text: str) -> set[str]:
    """Extract declared distributions from supported pyproject tables."""
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return set()

    names: set[str] = set()
    project = document.get("project") or {}
    for dependency in project.get("dependencies") or []:
        match = REQUIREMENT_NAME_RE.match(str(dependency).strip())
        if match:
            names.add(normalize_distribution(match.group(1)))
    for dependencies in (project.get("optional-dependencies") or {}).values():
        for dependency in dependencies or []:
            match = REQUIREMENT_NAME_RE.match(str(dependency).strip())
            if match:
                names.add(normalize_distribution(match.group(1)))

    poetry_dependencies = ((document.get("tool") or {}).get("poetry") or {}).get(
        "dependencies"
    ) or {}
    names.update(
        normalize_distribution(name)
        for name in poetry_dependencies
        if normalize_distribution(name) != "python"
    )
    for dependencies in (document.get("dependency-groups") or {}).values():
        for dependency in dependencies or []:
            match = REQUIREMENT_NAME_RE.match(str(dependency).strip())
            if match:
                names.add(normalize_distribution(match.group(1)))
    return names


def base_declared_distributions(
    repo_root: Path, base_sha: str, project_dir: str
) -> tuple[set[str], list[str]]:
    """Return distributions and manifests read only from the base commit."""
    directories = [project_dir]
    if project_dir != ".":
        directories.append(".")
    declared: set[str] = set()
    manifests: list[str] = []
    for directory in directories:
        for filename in (
            "requirements.txt",
            "requirements-hashes.txt",
            "pyproject.toml",
        ):
            relative_path = filename if directory == "." else f"{directory}/{filename}"
            text = git_show(repo_root, base_sha, relative_path)
            if text is None:
                continue
            manifests.append(relative_path)
            if filename == "pyproject.toml":
                declared.update(pyproject_names(text))
            else:
                declared.update(requirement_names(text))
    return declared, manifests


def missing_distributions(log_text: str) -> set[str]:
    """Return normalized missing distributions named by pytest collection."""
    distributions: set[str] = set()
    for module in MISSING_MODULE_RE.findall(log_text):
        import_root = normalize_distribution(module.split(".", 1)[0])
        distributions.add(IMPORT_DISTRIBUTION_ALIASES.get(import_root, import_root))
    return distributions


def classify(
    repo_root: Path,
    base_sha: str,
    project_dir: str,
    pytest_exit: int,
    log_file: Path,
) -> tuple[bool, str]:
    """Classify a failure, returning whether repository-native CI may own it."""
    if pytest_exit != 4:
        return False, f"pytest exit {pytest_exit} is not a collection failure"
    if log_file.is_symlink() or not log_file.is_file():
        return False, "pytest log is not a regular file"
    if log_file.stat().st_size > MAX_LOG_BYTES:
        return False, "pytest log exceeds the classifier size limit"

    log_text = log_file.read_text(encoding="utf-8", errors="replace")
    missing = missing_distributions(log_text)
    if not missing:
        return False, "collection failure did not name a missing Python module"
    terminal_exceptions = {
        exception.rsplit(".", 1)[-1]
        for exception in TERMINAL_EXCEPTION_RE.findall(log_text)
    }
    unexpected_exceptions = sorted(terminal_exceptions - {"ModuleNotFoundError"})
    if unexpected_exceptions:
        return False, "collection failure includes other exceptions: " + ", ".join(
            unexpected_exceptions
        )
    declared, manifests = base_declared_distributions(repo_root, base_sha, project_dir)
    undeclared = sorted(missing - declared)
    if undeclared:
        return (
            False,
            "missing modules are not base-declared dependencies: "
            + ", ".join(undeclared),
        )
    return True, (
        "networkless central coverage lacks base-declared dependencies "
        f"{', '.join(sorted(missing))}; trusted manifests: {', '.join(manifests)}; "
        "repository-native required checks remain authoritative"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse and validate command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--pytest-exit", type=int, required=True)
    parser.add_argument("--log-file", type=Path, required=True)
    args = parser.parse_args(argv)
    if not SHA_RE.fullmatch(args.base_sha):
        parser.error("--base-sha must be a 40-character git SHA")
    try:
        args.project_dir = validate_project_dir(args.project_dir)
    except ValueError as exc:
        parser.error(str(exc))
    args.repo_root = args.repo_root.resolve()
    if not (args.repo_root / ".git").exists():
        parser.error("--repo-root must name a Git worktree")
    # Preserve the final path component so classify() can reject a symlink
    # rather than silently following it to an attacker-selected file.
    args.log_file = Path(os.path.abspath(args.log_file))
    return args


def main(argv: list[str] | None = None) -> int:
    """Print a bounded classification and return zero only for safe deferral."""
    args = parse_args(argv)
    deferred, reason = classify(
        args.repo_root,
        args.base_sha,
        args.project_dir,
        args.pytest_exit,
        args.log_file,
    )
    status = "DEFERRED" if deferred else "BLOCKING"
    print(f"Python coverage dependency classification: {status}: {reason}")
    return 0 if deferred else 1


if __name__ == "__main__":
    raise SystemExit(main())
