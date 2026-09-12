"""Run review verification commands in an isolated scratch workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
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
    # Credential-bearing dotfiles/dirs a repo checkout can carry (npm/pip
    # registry tokens, git credential helpers, cloud/SSH/GPG config). The
    # sandboxed command's own workspace mount is writable, so anything copied
    # in here is both readable and tamperable by the command under test --
    # these must never ride along with an ordinary repo copy.
    ".env",
    ".env.*",
    ".envrc",
    # Note: DEFAULT_ENV_TEMPLATE_ALLOWLIST below carves committed,
    # secret-free dotenv templates back out of the ".env.*" glob above.
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".pgpass",
    ".git-credentials",
    ".ssh",
    ".gnupg",
    ".aws",
    ".kube",
    ".docker",
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
# Committed, secret-free dotenv templates. These match the ".env.*" glob in
# DEFAULT_IGNORE (which exists to exclude real credential-bearing dotenv
# variants such as ".env.local" or ".env.production") but carry no secrets
# themselves, so verification commands that read them for local defaults
# must still find them in the sandboxed copy.
DEFAULT_ENV_TEMPLATE_ALLOWLIST = (
    ".env.example",
    ".env.sample",
    ".env.template",
)
RESULT_MARKER = "SANDBOXED_VERIFY_RESULT"
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAXIMUM_SYMLINK_HOPS = 40


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the sandboxed verification wrapper."""
    parser = argparse.ArgumentParser(
        description=(
            "Copy the repository into a temporary workspace and run a verification command with a scrubbed environment."
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
    parser.add_argument(
        "--result-file",
        type=Path,
        help=(
            "Write the trusted result envelope to a new file and exact command "
            "streams to sibling .stdout/.stderr files instead of mixing evidence "
            "with command output."
        ),
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
    for path_key in (
        "HOME",
        "TMPDIR",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
    ):
        Path(env[path_key]).mkdir(parents=True, exist_ok=True)
    return env


def _reject_escaping_symlinks(destination: Path) -> None:
    """Fail closed if any symlink copied into the workspace resolves outside it.

    ``shutil.copytree(..., symlinks=True)`` preserves the exact target string
    of every symlink instead of dereferencing it, so a repository can carry a
    symlink whose (possibly absolute, possibly ``..``-laden) target resolves
    outside the copied tree. A command later run against the copy — under OS
    sandboxing or, in ``--isolation disabled`` debugging mode, directly on the
    host — must never be able to follow such a link to read or write a file
    outside the workspace boundary, defeating the isolation this module
    exists to provide. Every symlink under ``destination`` is walked hop by
    hop purely lexically (see ``_reject_escaping_symlink_chain``), so a link
    whose own target was itself excluded from the copy by ``DEFAULT_IGNORE``
    or ``extra_ignores`` -- or is simply broken -- is not confused with one
    that escapes; the first symlink found to actually escape, or whose chain
    cannot be resolved, aborts the whole copy rather than being silently
    dropped or repaired, since a repository author who plants one such link
    cannot be assumed not to have planted others.

    Walking starts from ``root`` -- ``destination`` fully resolved -- rather
    than ``destination`` itself, and every symlink found is then checked
    with ``path.relative_to(root)``. When some *ancestor* of ``destination``
    is itself reached through a symlink (for example a temp directory whose
    default OS location is a symlink, unrelated to anything the copied
    repository controls), ``destination`` and ``root`` are different, only
    lexically equal-looking strings for the same real location. Walking from
    the unresolved ``destination`` would then yield paths still prefixed
    with that unresolved string, which are never actually relative to
    ``root`` -- so ``relative_to`` raises before this function's own escape
    check ever runs, rejecting an entirely legitimate copy that contains no
    escaping symlink at all. Walking from ``root`` instead guarantees every
    yielded path already shares ``root``'s own resolved prefix, so
    ``relative_to`` only ever fails for the cases this function exists to
    reject.
    """
    root = destination.resolve(strict=True)
    for path in root.rglob("*"):
        if path.is_symlink():
            _resolve_symlink_components(
                path.relative_to(root).parts,
                root,
                root,
                set(),
                [MAXIMUM_SYMLINK_HOPS],
                path,
            )


def _resolve_symlink_components(
    parts: Sequence[str],
    resolved: Path,
    root: Path,
    active: set[Path],
    hops_remaining: list[int],
    candidate: Path,
) -> Path:
    """Resolve ``parts`` one component at a time, raising on escape or cycle.

    Uses ``os.readlink`` at every hop instead of ``Path.resolve()``, which
    requires the fully-resolved path to exist (``strict=True``) or is
    unreliable for detecting a cycle across Python versions (``strict=False``,
    the default) -- either way conflating a symlink escape with a symlink
    that merely points at a target this function never had to check for
    existence. A dangling target -- for example one whose file was excluded
    from the copy by ``DEFAULT_IGNORE`` -- is therefore accepted as long as
    it still resolves inside ``root``: verification must still run despite
    the broken link. Only an absolute target, a component that steps outside
    ``root``, or a chain that revisits a symlink it is *currently in the
    middle of following* (an unresolvable cycle) raises.

    Each path component is checked individually, and a component found to be
    a symlink is resolved via a recursive call, rather than resolving a whole
    target string in one ``os.path.normpath`` call -- a target can itself
    contain an intermediate component that is a symlink, for example
    ``some-alias/../secret`` where ``some-alias`` is itself a relative,
    entirely-legitimate-looking internal symlink. Collapsing that whole
    string lexically in one step would cancel ``some-alias`` against the
    following ``..`` textually, silently ignoring that following
    ``some-alias`` for real can land somewhere shallower or deeper than one
    directory level. Recursion is what makes the cycle check precise: a
    symlink is added to ``active`` only while its own target is being
    resolved and removed again as soon as that resolution returns
    successfully, so the *same* symlink referenced twice in one chain --
    once fully resolved before the second reference is ever reached, not a
    real loop -- is accepted, while a symlink that (directly or through
    others) points back to itself while still being resolved is rejected. A
    hop budget, shared across the whole recursive walk, bounds the total
    number of symlinks followed so a chain that never repeats still fails
    closed instead of walking forever; only actually dereferencing a symlink
    spends one unit of that budget, so a chain of exactly
    ``MAXIMUM_SYMLINK_HOPS`` real, resolvable symlinks is accepted.
    """
    for component in parts:
        if component == "..":
            if resolved == root:
                raise ValueError(f"workspace symlink escapes the sandbox root: {candidate}")
            resolved = resolved.parent
            continue
        step = resolved / component
        if not step.is_symlink():
            resolved = step
            continue
        if step in active:
            raise ValueError(f"workspace symlink could not be resolved: {candidate}")
        if hops_remaining[0] <= 0:
            raise ValueError(f"workspace symlink could not be resolved: {candidate}")
        active.add(step)
        hops_remaining[0] -= 1
        target = Path(os.readlink(step))
        if target.is_absolute():
            raise ValueError(f"workspace symlink escapes the sandbox root: {step} -> {target}")
        resolved = _resolve_symlink_components(target.parts, resolved, root, active, hops_remaining, candidate)
        active.discard(step)
    return resolved


def _ignore_with_env_template_allowlist(
    default_patterns: Sequence[str], extra_patterns: Sequence[str]
) -> Callable[[str, list[str]], set[str]]:
    """Build a ``copytree`` ignore function that spares committed env templates.

    ``shutil.ignore_patterns`` has no way to match a glob like ``.env.*``
    while excepting specific names from it, so a committed, secret-free
    template such as ``.env.example`` matches the same pattern used to
    exclude real credential-bearing dotenv files and would otherwise vanish
    from the sandboxed copy right along with them. This builds two
    *separate* pattern-based ignore functions -- one from ``default_patterns``
    (``DEFAULT_IGNORE``, whose broad ``.env.*`` glob the allowlist exists to
    carve an exception out of) and one from ``extra_patterns`` (a caller's
    explicit ``--ignore``/``extra_ignores``) -- and un-ignores a name found in
    ``DEFAULT_ENV_TEMPLATE_ALLOWLIST`` only when it was matched *solely* by
    the default patterns. A name the caller explicitly asked to exclude via
    ``extra_patterns`` -- for example because in their repository a file
    named ``.env.example`` happens to carry something sensitive despite the
    generic name -- stays excluded even though it is also one of the generic
    template names: the allowlist must never override an explicit caller
    exclusion, only the built-in broad glob.
    """
    default_ignore = shutil.ignore_patterns(*default_patterns)
    extra_ignore = shutil.ignore_patterns(*extra_patterns)

    def _ignore(directory: str, names: list[str]) -> set[str]:
        """Apply both pattern sets, sparing env template names not explicitly excluded."""
        default_ignored = default_ignore(directory, names)
        extra_ignored = extra_ignore(directory, names)
        protected = {
            name for name in default_ignored if name in DEFAULT_ENV_TEMPLATE_ALLOWLIST and name not in extra_ignored
        }
        return (default_ignored | extra_ignored) - protected

    return _ignore


def copy_workspace(repo_root: Path, sandbox_root: Path, extra_ignores: Sequence[str]) -> Path:
    """Copy the repository into the sandbox and return the copied root."""
    source = repo_root.resolve()
    if not source.is_dir():
        raise ValueError(f"repo root is not a directory: {source}")
    destination = sandbox_root / "repo"
    ignore = _ignore_with_env_template_allowlist(DEFAULT_IGNORE, tuple(extra_ignores))
    shutil.copytree(source, destination, ignore=ignore, symlinks=True)
    _reject_escaping_symlinks(destination)
    return destination


def run_command(
    command: Sequence[str], cwd: Path, env: dict[str, str], timeout: int
) -> subprocess.CompletedProcess[bytes]:
    """Run the verification command and capture output for review evidence."""
    return subprocess.run(
        list(command),
        cwd=cwd,
        env=env,
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


def _output_bytes(value: str | bytes | None) -> bytes:
    """Normalize captured command output without altering subprocess bytes."""
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    return value.encode()


def _forward_bytes(stream: object, output: bytes) -> None:
    """Forward command bytes exactly when the active stream exposes a buffer."""
    if not output:
        return
    binary_stream = getattr(stream, "buffer", None)
    if binary_stream is not None:
        binary_stream.write(output)
        binary_stream.flush()
        return
    stream.write(output.decode(errors="replace"))  # type: ignore[attr-defined]
    stream.flush()  # type: ignore[attr-defined]


def _open_result_parent(parent: Path) -> int:
    """Open/create ``parent`` component-wise without following symlinks."""
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    if parent.is_absolute():
        directory_fd = os.open(os.path.sep, directory_flags)
        components = parent.parts[1:]
    else:
        directory_fd = os.open(".", directory_flags)
        components = parent.parts
    try:
        for component in components:
            if component in ("", "."):
                continue
            if component == "..":
                raise ValueError(f"result file parent is not a regular directory: {parent}")
            try:
                next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            except FileNotFoundError:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=directory_fd)
                except FileExistsError:
                    pass
                try:
                    next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
                except OSError as exc:
                    raise ValueError(f"result file parent is not a regular directory: {parent}") from exc
            except OSError as exc:
                raise ValueError(f"result file parent is not a regular directory: {parent}") from exc
            os.close(directory_fd)
            directory_fd = next_fd
        return directory_fd
    except BaseException:
        os.close(directory_fd)
        raise


def _write_all(file_descriptor: int, content: bytes) -> None:
    """Write all ``content`` to an already-open file descriptor."""
    offset = 0
    while offset < len(content):
        offset += os.write(file_descriptor, content[offset:])


def _write_result_bundle(result_file: Path, rendered_result: bytes, stdout_bytes: bytes, stderr_bytes: bytes) -> None:
    """Create the trusted envelope and streams through one safe parent handle."""
    parent_fd = _open_result_parent(result_file.parent)
    stdout_name = result_file.name + ".stdout"
    stderr_name = result_file.name + ".stderr"
    bundle = (
        (stdout_name, stdout_bytes),
        (stderr_name, stderr_bytes),
        (result_file.name, rendered_result),
    )
    created_names: list[str] = []
    open_descriptors: list[int] = []
    file_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        try:
            os.stat(result_file.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError(f"result file already exists: {result_file}")
        for file_name, _ in bundle:
            try:
                file_descriptor = os.open(file_name, file_flags, 0o600, dir_fd=parent_fd)
            except FileExistsError as exc:
                raise ValueError(f"result bundle file already exists: {result_file.parent / file_name}") from exc
            open_descriptors.append(file_descriptor)
            created_names.append(file_name)
        for file_descriptor, (_, content) in zip(open_descriptors, bundle, strict=True):
            _write_all(file_descriptor, content)
    except BaseException:
        for file_name in created_names:
            try:
                os.unlink(file_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        raise
    finally:
        for file_descriptor in open_descriptors:
            os.close(file_descriptor)
        os.close(parent_fd)


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
    result_file: Path | None = None,
    result_state: str = "completed",
    timed_out: bool = False,
    stdout_bytes: bytes = b"",
    stderr_bytes: bytes = b"",
) -> None:
    """Write a versioned execution envelope and its exact command streams."""
    stdout_name = result_file.name + ".stdout" if result_file is not None else None
    stderr_name = result_file.name + ".stderr" if result_file is not None else None
    payload = {
        "allowed_env": sorted(set(allowed_env)),
        "command": list(command),
        "cwd": str(copied_repo),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "evidence_note": evidence_note,
        "exit_code": exit_code,
        "helper_id": "ContextualWisdomLab/.github:sandboxed_verify",
        "isolation": {
            "network_enforced": False,
            "os_process_isolation": "none",
            "workspace": "copy+scrubbed-env",
        },
        "network": network,
        "result_state": result_state,
        "runtime": {
            "implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
        },
        "sandbox": str(sandbox_root) if kept else "(removed)",
        "sandboxed": True,
        "schema": "sandboxed_verify.execution.v1",
        "stderr": {
            "file": stderr_name,
            "sha256": hashlib.sha256(stderr_bytes).hexdigest(),
            "size_bytes": len(stderr_bytes),
        },
        "stdout": {
            "file": stdout_name,
            "sha256": hashlib.sha256(stdout_bytes).hexdigest(),
            "size_bytes": len(stdout_bytes),
        },
        "timed_out": timed_out,
    }
    rendered = f"{RESULT_MARKER} {json.dumps(payload, sort_keys=True)}\n"
    if result_file is None:
        print(rendered, end="")
        return
    _write_result_bundle(result_file, rendered.encode(), stdout_bytes, stderr_bytes)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the verification command exit code."""
    args = parse_args(argv)
    sandbox = Path(tempfile.mkdtemp(prefix="sandboxed-verify-"))
    start = time.monotonic()
    exit_code = 1
    copied_repo = sandbox / "repo"
    result_state = "internal_error"
    command_stdout = b""
    command_stderr = b""
    try:
        try:
            copied_repo = copy_workspace(Path(args.repo_root), sandbox, args.ignore)
        except ValueError as exc:
            print(f"sandboxed-verify: workspace copy rejected: {exc}", file=sys.stderr)
            exit_code = 125
            result_state = "copy_rejected"
        else:
            env = scrubbed_env(sandbox, args.allow_env)
            print(f"sandboxed-verify: cwd={copied_repo}")
            print(f"sandboxed-verify: command={' '.join(args.command)}")
            if args.allow_env:
                print(f"sandboxed-verify: allowed env names={','.join(sorted(set(args.allow_env)))}")
            if args.network != "default":
                print(f"sandboxed-verify: network={args.network}")
            try:
                completed = run_command(args.command, copied_repo, env, args.timeout)
                command_stdout = _output_bytes(completed.stdout)
                command_stderr = _output_bytes(completed.stderr)
                _forward_bytes(sys.stdout, command_stdout)
                _forward_bytes(sys.stderr, command_stderr)
                exit_code = completed.returncode
                result_state = "completed"
            except subprocess.TimeoutExpired as exc:
                command_stdout = _output_bytes(exc.stdout)
                command_stderr = _output_bytes(exc.stderr)
                _forward_bytes(sys.stdout, command_stdout)
                _forward_bytes(sys.stderr, command_stderr)
                print(
                    f"sandboxed-verify: command timed out after {args.timeout}s",
                    file=sys.stderr,
                )
                exit_code = 124
                result_state = "timed_out"
    finally:
        elapsed = time.monotonic() - start
        try:
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
                result_file=args.result_file,
                result_state=result_state,
                timed_out=result_state == "timed_out",
                stdout_bytes=command_stdout,
                stderr_bytes=command_stderr,
            )
        except (OSError, ValueError) as exc:
            diagnostic = str(exc).splitlines()[0][:240]
            print(
                f"sandboxed-verify: result evidence rejected: {diagnostic}",
                file=sys.stderr,
            )
            # Evidence rejection is the primary failure only when the command
            # itself succeeded. Preserve an existing command, timeout, or copy
            # rejection status so callers do not lose the causal exit code.
            if exit_code == 0:
                exit_code = 125
        finally:
            if not args.keep_sandbox:
                shutil.rmtree(sandbox, ignore_errors=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
