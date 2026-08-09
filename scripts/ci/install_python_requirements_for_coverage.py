"""Install target Python requirements for coverage evidence with visible policy logs."""

from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys


def _requirement_lines(path: pathlib.Path) -> list[str]:
    """Return non-empty, non-comment requirement lines."""
    lines: list[str] = []
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def _has_hash_pins(path: pathlib.Path) -> bool:
    """Return whether a requirements file carries hash-checking intent."""
    lines = _requirement_lines(path)
    if not lines:
        return True
    return any(line == "--require-hashes" for line in lines) or all(
        "--hash=" in line or line.startswith(("-r ", "--requirement "))
        for line in lines
    )


def _run(command: list[str], cwd: pathlib.Path) -> int:
    """Run one installer command from a target project directory."""
    print("+ " + " ".join(command), flush=True)
    return subprocess.run(command, cwd=cwd, check=False, shell=False).returncode  # nosec B603


def _install_hash_pinned(requirements: pathlib.Path, cwd: pathlib.Path) -> int:
    """Install hash-pinned Python requirements using pip."""
    print(
        f"Installing hash-pinned Python requirements from {requirements}.",
        flush=True,
    )
    return _run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--require-hashes",
            "-r",
            str(requirements),
        ],
        cwd,
    )


def _install_unpinned_with_uv(requirements: pathlib.Path, cwd: pathlib.Path, uv_path: str) -> int:
    """Install unpinned requirements using uv, warning about lack of hashes."""
    print(
        "::warning::Target requirements are not hash-pinned; using uv for "
        "coverage-only dependency materialization in a read-only/no-secret job.",
        flush=True,
    )
    return _run([uv_path, "pip", "install", "--system", "-r", str(requirements)], cwd)


def main(argv: list[str] | None = None) -> int:
    """Install one target requirements file under the coverage policy."""
    parser = argparse.ArgumentParser()
    parser.add_argument("requirements", type=pathlib.Path)
    args = parser.parse_args(argv)

    requirements = args.requirements.resolve()
    if not requirements.is_file():
        print(f"::error::requirements file not found: {requirements}", file=sys.stderr)
        return 2

    cwd = requirements.parent
    if _has_hash_pins(requirements):
        return _install_hash_pinned(requirements, cwd)

    if uv := shutil.which("uv"):
        return _install_unpinned_with_uv(requirements, cwd, uv)

    print(
        "::error::Target requirements are not hash-pinned and uv is unavailable; "
        "refusing unpinned pip install. Add --hash pins or a lock-backed pyproject "
        "so coverage evidence can install dependencies safely.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
