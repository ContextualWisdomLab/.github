"""Run review verification commands in an isolated scratch workspace."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path


DEFAULT_IGNORE = (
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".coverage",
    "coverage.xml",
    "htmlcov",
    "dist",
    "build",
)
SECRET_ENV_TOKENS = (
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
    "AUTH",
    "PRIVATE_KEY",
    "ACCESS_KEY",
    "SESSION_KEY",
)
SAFE_ENV_ALLOWLIST = (
    "PATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "SHELL",
    "TERM",
    "TZ",
    "PYTHONPATH",
)
RESULT_MARKER = "SANDBOXED_VERIFY_RESULT"
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the sandboxed verification wrapper."""
    parser = argparse.ArgumentParser(
        description=(
            "Copy the repository into a temporary workspace and run a verification "
            "command with a scrubbed environment."
        )
    )
    parser.add_argument("--repo-root", default=".", help="Repository root to copy into the sandbox.")
    parser.add_argument("--timeout", type=int, default=300, help="Command timeout in seconds.")
    parser.add_argument(
        "--keep-sandbox",
        action="store_true",
        help="Keep the temporary sandbox for debugging and print its path in the result.",
    )
    parser.add_argument(
        "--ignore",
        action="append",
        default=[],
        help="Additional basename or glob-like directory entries to exclude from the sandbox copy.",
    )
    parser.add_argument(
        "--allow-env",
        action="append",
        default=[],
        metavar="NAME",
        help="Pass one named environment variable into the sandbox. Values are never printed.",
    )
    parser.add_argument(
        "--network",
        choices=("default", "required", "not-required"),
        default="default",
        help="Declare whether this verification requires network access. This records evidence metadata; it does not enforce OS-level network policy.",
    )
    parser.add_argument(
        "--evidence-note",
        default="",
        help="Short reviewer note explaining why network or allowed env variables are needed.",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Verification command after --.")
    args = parser.parse_args(argv)
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("provide a verification command after --")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    for name in args.allow_env:
        if not ENV_NAME_RE.match(name):
            parser.error(f"--allow-env must be an environment variable name: {name}")
    return args


def scrubbed_env(sandbox_root: Path, allow_env: Sequence[str] = ()) -> dict[str, str]:
    """Return an environment with temp-scoped homes and allowlisted secrets."""
    env: dict[str, str] = {}
    allowed = set(allow_env)
    for key, value in os.environ.items():
        upper_key = key.upper()
        if key in allowed:
            env[key] = value
        elif key in SAFE_ENV_ALLOWLIST and not any(token in upper_key for token in SECRET_ENV_TOKENS):
            env[key] = value
    env.update(
        {
            "CI": "true",
            "SANDBOXED_VERIFY": "1",
            "HOME": str(sandbox_root / "home"),
            "TMPDIR": str(sandbox_root / "tmp"),
            "XDG_CACHE_HOME": str(sandbox_root / "xdg-cache"),
            "XDG_CONFIG_HOME": str(sandbox_root / "xdg-config"),
            "XDG_DATA_HOME": str(sandbox_root / "xdg-data"),
        }
    )
    for path_key in ("HOME", "TMPDIR", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
        Path(env[path_key]).mkdir(parents=True, exist_ok=True)
    return env


def copy_workspace(repo_root: Path, sandbox_root: Path, extra_ignores: Sequence[str]) -> Path:
    """Copy the repository into the sandbox and return the copied root."""
    source = repo_root.resolve()
    if not source.is_dir():
        raise ValueError(f"repo root is not a directory: {source}")
    destination = sandbox_root / "repo"
    ignore = shutil.ignore_patterns(*(DEFAULT_IGNORE + tuple(extra_ignores)))
    shutil.copytree(source, destination, ignore=ignore, symlinks=True)
    return destination


def run_command(command: Sequence[str], cwd: Path, env: dict[str, str], timeout: int) -> subprocess.CompletedProcess[str]:
    """Run the verification command and capture output for review evidence."""
    return subprocess.run(
        list(command),
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        shell=False,
    )


def timeout_output_text(value: str | bytes | None) -> str:
    """Return timeout output as text, regardless of subprocess internals."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def emit_result(
    *,
    command: Sequence[str],
    copied_repo: Path,
    sandbox_root: Path,
    exit_code: int,
    elapsed_seconds: float,
    kept: bool,
    allowed_env: Sequence[str],
    network: str,
    evidence_note: str,
) -> None:
    """Print a machine-readable execution evidence summary."""
    payload = {
        "allowed_env": sorted(set(allowed_env)),
        "command": list(command),
        "cwd": str(copied_repo),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "evidence_note": evidence_note,
        "exit_code": exit_code,
        "network": network,
        "sandbox": str(sandbox_root) if kept else "(removed)",
        "sandboxed": True,
    }
    print(f"{RESULT_MARKER} {json.dumps(payload, sort_keys=True)}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the verification command exit code."""
    args = parse_args(argv)
    sandbox = Path(tempfile.mkdtemp(prefix="sandboxed-verify-"))
    start = time.monotonic()
    exit_code = 1
    copied_repo = sandbox / "repo"
    try:
        copied_repo = copy_workspace(Path(args.repo_root), sandbox, args.ignore)
        env = scrubbed_env(sandbox, args.allow_env)
        print(f"sandboxed-verify: cwd={copied_repo}")
        print(f"sandboxed-verify: command={' '.join(args.command)}")
        if args.allow_env:
            print(f"sandboxed-verify: allowed env names={','.join(sorted(set(args.allow_env)))}")
        if args.network != "default":
            print(f"sandboxed-verify: network={args.network}")
        try:
            completed = run_command(args.command, copied_repo, env, args.timeout)
            if completed.stdout:
                print(completed.stdout, end="")
            if completed.stderr:
                print(completed.stderr, end="", file=sys.stderr)
            exit_code = completed.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = timeout_output_text(exc.stdout)
            stderr = timeout_output_text(exc.stderr)
            if stdout:
                print(stdout, end="" if stdout.endswith("\n") else "\n")
            if stderr:
                print(stderr, end="" if stderr.endswith("\n") else "\n", file=sys.stderr)
            print(f"sandboxed-verify: command timed out after {args.timeout}s", file=sys.stderr)
            exit_code = 124
        return exit_code
    finally:
        elapsed = time.monotonic() - start
        emit_result(
            command=args.command,
            copied_repo=copied_repo,
            sandbox_root=sandbox,
            exit_code=exit_code,
            elapsed_seconds=elapsed,
            kept=args.keep_sandbox,
            allowed_env=args.allow_env,
            network=args.network,
            evidence_note=args.evidence_note,
        )
        if not args.keep_sandbox:
            shutil.rmtree(sandbox, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
