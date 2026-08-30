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

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.ci import bounded_subprocess


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
MAXIMUM_SYMLINK_HOPS = 40
RESULT_MARKER = "SANDBOXED_VERIFY_RESULT"
PATH_BOUNDARY_EXIT_CODE = 122
COMMAND_NOT_EXECUTABLE_EXIT_CODE = 126
COMMAND_NOT_FOUND_EXIT_CODE = 127
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class RepositoryPathBoundaryError(ValueError):
    """Report a copied repository link that escapes its sandbox boundary."""


class RepositoryRootError(ValueError):
    """Report that the requested repository root cannot be copied."""


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
        "--output-limit-bytes",
        type=int,
        default=bounded_subprocess.DEFAULT_COMMAND_OUTPUT_LIMIT_BYTES,
        help="Maximum retained stdout and stderr bytes per stream.",
    )
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
    try:
        args.output_limit_bytes = bounded_subprocess.validate_output_limit(
            args.output_limit_bytes,
            "--output-limit-bytes",
        )
    except ValueError as error:
        parser.error(str(error))
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


def _validate_contained_symlink_cycle(candidate: Path, source_root: Path) -> None:
    """Accept a repository-internal symlink cycle, rejecting only an escape.

    ``Path.resolve(strict=False)`` raises an uncaught ``RuntimeError`` for a
    symlink loop -- even one fully self-contained inside the copied
    repository -- before ``validate_repository_symlinks`` can classify it.
    This walks the same chain by hand, one ``os.readlink`` hop at a time,
    tracking visited paths itself instead of asking the filesystem to
    resolve indefinitely. A hop whose target is absolute, or whose lexically
    normalized target steps outside ``source_root``, still raises
    ``RepositoryPathBoundaryError`` exactly like a non-cyclic escape. A chain
    that revisits a path it already followed -- without ever leaving
    ``source_root`` -- is treated as contained and returns normally. The hop
    count is bounded so a chain that (due to purely lexical, not real-path,
    normalization) never repeats still fails closed instead of hanging.
    """
    visited: set[Path] = set()
    current = Path(os.path.normpath(candidate))
    for _ in range(MAXIMUM_SYMLINK_HOPS):
        if current in visited:
            return
        visited.add(current)
        if not current.is_symlink():
            return
        target = Path(os.readlink(current))
        if target.is_absolute():
            raise RepositoryPathBoundaryError(
                f"symlink escapes repository verification sandbox via absolute target: "
                f"{current} -> {target}"
            )
        current = Path(os.path.normpath(current.parent / target))
        try:
            current.relative_to(source_root)
        except ValueError as exc:
            raise RepositoryPathBoundaryError(
                f"symlink escapes repository verification sandbox: {candidate} -> {target}"
            ) from exc
    raise RepositoryPathBoundaryError(
        f"symlink chain exceeds the supported hop limit: {candidate}"
    )


def validate_repository_symlinks(source: Path) -> None:
    """Reject symlinks that could escape the copied repository sandbox.

    Relative links are retained only when their resolved target stays beneath
    ``source``. Absolute links are rejected even when they currently name a
    path beneath ``source`` because preserving them would point the sandboxed
    command back at the original checkout instead of the isolated copy. A
    symlink cycle fully contained beneath ``source`` (see
    ``_validate_contained_symlink_cycle``) is accepted rather than aborting
    verification with an uncaught ``RuntimeError``.
    """
    source_root = source.resolve(strict=True)
    for current_root, directory_names, file_names in os.walk(source_root, followlinks=False):
        current = Path(current_root)
        for name in (*directory_names, *file_names):
            candidate = current / name
            if not candidate.is_symlink():
                continue
            target = Path(os.readlink(candidate))
            if target.is_absolute():
                raise RepositoryPathBoundaryError(
                    f"symlink escapes repository verification sandbox via absolute target: "
                    f"{candidate} -> {target}"
                )
            try:
                resolved_target = (candidate.parent / target).resolve(strict=False)
            except RuntimeError:
                _validate_contained_symlink_cycle(candidate, source_root)
                continue
            try:
                resolved_target.relative_to(source_root)
            except ValueError as exc:
                raise RepositoryPathBoundaryError(
                    f"symlink escapes repository verification sandbox: {candidate} -> {target}"
                ) from exc


def copy_workspace(repo_root: Path, sandbox_root: Path, extra_ignores: Sequence[str]) -> Path:
    """Copy the repository into the sandbox and return the copied root."""
    source = repo_root.resolve()
    if not source.is_dir():
        raise RepositoryRootError(f"repo root is not a directory: {source}")
    destination = sandbox_root / "repo"
    ignore = shutil.ignore_patterns(*(DEFAULT_IGNORE + tuple(extra_ignores)))
    shutil.copytree(source, destination, ignore=ignore, symlinks=True)
    validate_repository_symlinks(destination)
    return destination


def run_command(
    command: Sequence[str],
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    output_limit_bytes: int = bounded_subprocess.DEFAULT_COMMAND_OUTPUT_LIMIT_BYTES,
) -> bounded_subprocess.BoundedCompletedProcess:
    """Run one verification command with continuously drained bounded output."""
    return bounded_subprocess.run_bounded_command(
        command,
        cwd=cwd,
        env=env,
        timeout=timeout,
        evidence_limit_bytes=output_limit_bytes,
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
    output_limit_bytes: int = bounded_subprocess.DEFAULT_COMMAND_OUTPUT_LIMIT_BYTES,
    output_limited: bool = False,
    output_limit_unsupported: bool = False,
    path_boundary_rejected: bool = False,
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
        "output_limit_bytes": output_limit_bytes,
        "output_limited": output_limited,
        "output_limit_unsupported": output_limit_unsupported,
        "path_boundary_rejected": path_boundary_rejected,
        "sandbox": str(sandbox_root) if kept else "(removed)",
        "sandboxed": True,
    }
    print()
    print(f"{RESULT_MARKER} {json.dumps(payload, sort_keys=True)}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the verification command exit code."""
    args = parse_args(argv)
    sandbox = Path(tempfile.mkdtemp(prefix="sandboxed-verify-"))
    start = time.monotonic()
    exit_code = 1
    output_limited = False
    output_limit_unsupported = False
    path_boundary_rejected = False
    copied_repo = sandbox / "repo"
    try:
        try:
            copied_repo = copy_workspace(Path(args.repo_root), sandbox, args.ignore)
        except RepositoryPathBoundaryError:
            path_boundary_rejected = True
            copied_repo = Path("(not-created)")
            print(
                "sandboxed-verify: repository path boundary rejected",
                file=sys.stderr,
            )
            exit_code = PATH_BOUNDARY_EXIT_CODE
            return exit_code
        except RepositoryRootError:
            copied_repo = Path("(not-created)")
            print(
                "sandboxed-verify: repository root is not a directory",
                file=sys.stderr,
            )
            exit_code = 1
            return exit_code
        env = scrubbed_env(sandbox, args.allow_env)
        print(f"sandboxed-verify: cwd={copied_repo}")
        print(f"sandboxed-verify: command={' '.join(args.command)}")
        if args.allow_env:
            print(f"sandboxed-verify: allowed env names={','.join(sorted(set(args.allow_env)))}")
        if args.network != "default":
            print(f"sandboxed-verify: network={args.network}")
        try:
            completed = run_command(
                args.command,
                copied_repo,
                env,
                args.timeout,
                args.output_limit_bytes,
            )
            if completed.stdout:
                print(completed.stdout, end="")
            if completed.stderr:
                print(completed.stderr, end="", file=sys.stderr)
            output_limited = completed.output_limited
            if output_limited:
                print(
                    "sandboxed-verify: command output exceeded "
                    f"{args.output_limit_bytes} bytes",
                    file=sys.stderr,
                )
                exit_code = bounded_subprocess.OUTPUT_LIMIT_EXIT_CODE
            else:
                exit_code = completed.returncode
        except FileNotFoundError:
            print(
                "sandboxed-verify: install the executable or correct command PATH",
                file=sys.stderr,
            )
            exit_code = COMMAND_NOT_FOUND_EXIT_CODE
        except (PermissionError, IsADirectoryError):
            print(
                "sandboxed-verify: select an executable file or correct its permissions",
                file=sys.stderr,
            )
            exit_code = COMMAND_NOT_EXECUTABLE_EXIT_CODE
        except bounded_subprocess.OutputLimitUnsupportedError:
            output_limit_unsupported = True
            print(
                "sandboxed-verify: bounded child output is unavailable on this platform",
                file=sys.stderr,
            )
            exit_code = bounded_subprocess.OUTPUT_LIMIT_EXIT_CODE
        except (OSError, RuntimeError):
            print(
                "sandboxed-verify: bounded output capture failed",
                file=sys.stderr,
            )
            exit_code = bounded_subprocess.OUTPUT_LIMIT_EXIT_CODE
        except subprocess.TimeoutExpired as exc:
            stdout = timeout_output_text(exc.stdout)
            stderr = timeout_output_text(exc.stderr)
            if stdout:
                print(stdout, end="" if stdout.endswith("\n") else "\n")
            if stderr:
                print(stderr, end="" if stderr.endswith("\n") else "\n", file=sys.stderr)
            output_limited = bool(getattr(exc, "output_limited", False))
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
            output_limit_bytes=args.output_limit_bytes,
            output_limited=output_limited,
            output_limit_unsupported=output_limit_unsupported,
            path_boundary_rejected=path_boundary_rejected,
        )
        if not args.keep_sandbox:
            shutil.rmtree(sandbox, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
