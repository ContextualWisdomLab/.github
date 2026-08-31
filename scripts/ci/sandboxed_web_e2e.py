"""Run backend, frontend, and E2E commands in an isolated workspace."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import platform
import signal
import shutil
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.ci import sandboxed_verify


RESULT_MARKER = "SANDBOXED_WEB_E2E_RESULT"
SANDBOX_MOUNT = "/workspace"


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Explicitly disable redirects to prevent SSRF bypasses via 301/302 to local IPs."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Raise an HTTPError instead of following the redirect."""
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


@dataclass
class Service:
    """A long-running web service process and its log file."""

    label: str
    command: str
    process: subprocess.Popen[str]
    log_path: Path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for sandboxed web E2E execution."""
    parser = argparse.ArgumentParser(
        description=(
            "Copy a repository into a temporary workspace, start backend and "
            "frontend commands, wait for readiness URLs, run an E2E command, "
            "and clean up services."
        )
    )
    parser.add_argument("--repo-root", default=".", help="Repository root to copy into the sandbox.")
    parser.add_argument("--backend-cmd", required=True, help="Shell command that starts the backend service.")
    parser.add_argument("--frontend-cmd", required=True, help="Shell command that starts the frontend service.")
    parser.add_argument("--e2e-cmd", required=True, help="Shell command that runs the E2E test.")
    parser.add_argument("--backend-ready-url", default="", help="Backend readiness URL to poll before E2E.")
    parser.add_argument("--frontend-ready-url", default="", help="Frontend readiness URL to poll before E2E.")
    parser.add_argument("--startup-timeout", type=int, default=120, help="Seconds to wait for readiness URLs.")
    parser.add_argument("--e2e-timeout", type=int, default=600, help="Seconds to allow the E2E command to run.")
    parser.add_argument("--keep-sandbox", action="store_true", help="Keep the temporary sandbox after execution.")
    parser.add_argument(
        "--isolation",
        choices=("required", "disabled"),
        default="required",
        help=(
            "Require a bubblewrap OS sandbox (the default). Use disabled only for "
            "trusted local debugging when bubblewrap is unavailable."
        ),
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
        help="Declare whether this E2E run requires network access. This records evidence metadata; it does not enforce OS-level network policy.",
    )
    parser.add_argument(
        "--evidence-note",
        default="",
        help="Short reviewer note explaining why network or allowed env variables are needed.",
    )
    parser.add_argument(
        "--ignore",
        action="append",
        default=[],
        help="Additional basename or glob-like directory entries to exclude from the sandbox copy.",
    )
    args = parser.parse_args(argv)
    if args.startup_timeout <= 0:
        parser.error("--startup-timeout must be positive")
    if args.e2e_timeout <= 0:
        parser.error("--e2e-timeout must be positive")
    for name in args.allow_env:
        if not sandboxed_verify.ENV_NAME_RE.match(name):
            parser.error(f"--allow-env must be an environment variable name: {name}")
    for flag, value in (
        ("--backend-cmd", args.backend_cmd),
        ("--frontend-cmd", args.frontend_cmd),
        ("--e2e-cmd", args.e2e_cmd),
    ):
        _require_parseable_command(parser, flag, value)
    return args


def _require_parseable_command(parser: argparse.ArgumentParser, flag: str, value: str) -> None:
    """Reject a command that fails to shell-tokenize or tokenizes to nothing.

    ``isolated_command`` performs this exact ``shlex.split`` validation
    itself, but only reaches it when isolation is enabled. With
    ``--isolation disabled`` (the explicit, documented "trusted local
    debugging" escape hatch), a command string bypasses ``isolated_command``
    entirely and is handed straight to ``start_service``/``run_shell``, which
    call ``shlex.split`` directly with no ``except`` around either call. A
    blank command, or one with an unmatched shell-quote character, then
    raised an uncaught ``ValueError`` from deep inside ``main`` instead of
    the clean, coded CLI failure every other bad input in this module
    produces. Validating here, in ``parse_args``, runs for both isolation
    modes -- disabled included -- so a malformed command is always rejected
    the same way, through argparse's own clean-exit path, before ``main``
    ever tries to run it.
    """
    try:
        tokens = shlex.split(value)
    except ValueError as exc:
        parser.error(f"{flag} is not a valid shell command: {exc}")
    else:
        if not tokens:
            parser.error(f"{flag} must not be blank")


BIND_ROOTS = ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/opt")


def _bind_roots() -> list[Path]:
    """Return the read-only host runtime roots bubblewrap mounts, if present."""
    return [Path(path) for path in BIND_ROOTS if Path(path).exists()]


# Common system shell locations that live under BIND_ROOTS -- the only host
# paths isolated_command actually bind-mounts read-only into the sandbox.
# Covers both a traditional split /bin and /usr/bin and a merged-/usr layout
# where /bin is itself a symlink into /usr/bin.
PROBE_SHELL_PATHS = ("/bin/sh", "/usr/bin/sh")


def _probe_shell() -> str:
    """Pick a probe shell that is guaranteed to be visible inside the sandbox.

    ``isolated_command`` only ever bind-mounts ``BIND_ROOTS`` (plus a small
    fixed set of ``/etc`` files) read-only into the sandbox. Resolving the
    probe shell from the caller's own ``PATH`` -- as opposed to this fixed,
    known-mounted set -- can return a binary that lives outside every mounted
    root, for example when a ``PATH`` entry earlier than the system one
    shadows ``sh`` with a home-directory executable. Such a shell is invisible
    inside the sandbox, so the probe fails even though a real invocation
    using an actually-mounted shell would succeed, misclassifying a working
    host as one with isolation unavailable. Restricting the choice to
    ``PROBE_SHELL_PATHS`` keeps the probe representative of what a real
    isolated command can execute. Failure to find any of them is reported
    clearly instead of silently substituting an unvalidated fallback.
    """
    for candidate in PROBE_SHELL_PATHS:
        path = Path(candidate)
        if path.is_file() and os.access(path, os.X_OK):
            return candidate
    raise RuntimeError(
        "bubblewrap capability probe needs a system shell at one of: "
        f"{', '.join(PROBE_SHELL_PATHS)}"
    )


def _probe_isolation_capability(backend: str) -> None:
    """Prove bubblewrap can create the sandbox namespaces before any service starts.

    A discovered ``bwrap`` binary on PATH only proves the tool is installed;
    it does not prove the host actually permits creating the unprivileged
    user, PID, and mount namespaces bubblewrap depends on. A restricted Linux
    host (for example one with unprivileged user namespaces disabled, or a
    seccomp policy that denies ``unshare``/``clone``) can have a working
    ``bwrap`` binary that still fails on every real invocation. This mirrors
    every operation ``isolated_command`` actually performs -- new-session
    creation, the new PID namespace, tmpfs root, the standard read-only
    binds, ``/proc``, ``/dev``, a tmpfs ``/tmp``, and a writable bind+chdir
    into the same mount point real commands run from -- against a real
    (throwaway) temp directory, so a host that permits a reduced probe but
    denies one of these still-untested operations is classified as
    unavailable isolation (exit code 126) up front, instead of surfacing
    later as a confusing service-readiness or test failure.
    """
    probe_executable = _probe_shell()
    bind_args: list[str] = []
    for root in _bind_roots():
        bind_args.extend(("--ro-bind", str(root), str(root)))
    with tempfile.TemporaryDirectory(prefix="sandboxed-web-e2e-probe-") as probe_workspace:
        probe_command = [
            backend,
            "--die-with-parent",
            "--new-session",
            "--unshare-pid",
            "--tmpfs",
            "/",
            *bind_args,
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--bind",
            probe_workspace,
            SANDBOX_MOUNT,
            "--chdir",
            SANDBOX_MOUNT,
            "--",
            probe_executable,
            "-c",
            f"test -w {SANDBOX_MOUNT} && test -w /tmp",
        ]
        try:
            result = subprocess.run(
                probe_command,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"bubblewrap capability probe could not run: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        raise RuntimeError(f"bubblewrap cannot create required namespaces: {detail}")


def isolation_backend(mode: str) -> str | None:
    """Resolve the requested OS isolation backend without silently downgrading."""
    if mode == "disabled":
        return None
    if platform.system() != "Linux":
        raise RuntimeError("required isolation is only supported on Linux with bubblewrap")
    backend = shutil.which("bwrap")
    if backend is None:
        raise RuntimeError("required isolation needs bubblewrap (bwrap) on PATH")
    _probe_isolation_capability(backend)
    return backend


def _sandbox_environment(env: dict[str, str], sandbox_root: Path) -> dict[str, str]:
    """Map host sandbox paths to the path exposed inside the bubblewrap mount."""
    source = str(sandbox_root)
    mapped = dict(env)
    for key in ("HOME", "TMPDIR", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
        value = mapped.get(key)
        if value:
            mapped[key] = value.replace(source, SANDBOX_MOUNT, 1)
    path_value = mapped.get("PATH")
    if path_value:
        mapped["PATH"] = os.pathsep.join(
            _translate_sandbox_path_entry(entry, source) for entry in path_value.split(os.pathsep)
        )
    return mapped


def _translate_sandbox_path_entry(entry: str, source: str) -> str:
    """Rewrite one ``PATH`` entry rooted under the host sandbox copy into its ``/workspace`` form.

    A command that relies on ``PATH`` lookup for a workspace-local binary
    (rather than naming it by an explicit path) is launched with the *host*
    copy's absolute path still present in its inherited ``PATH`` -- the same
    host path ``isolated_command`` resolves it against for validation, but
    one that does not exist inside the bubblewrap mount, where only
    ``SANDBOX_MOUNT`` is bound. An entry that is not rooted under the sandbox
    copy (for example a bind-mounted system directory like ``/usr/bin``) is
    returned unchanged, matching how ``HOME``/``TMPDIR`` and friends above
    are left alone when they do not reference the sandbox copy either.
    """
    if entry == source or entry.startswith(source + os.sep):
        return entry.replace(source, SANDBOX_MOUNT, 1)
    return entry


def _which_relative_to_cwd(argv0: str, *, cwd: Path, sandbox_root: Path, path: str | None) -> Path | None:
    """Search ``PATH`` for ``argv0`` like ``shutil.which``, anchoring relative entries at ``cwd``.

    ``shutil.which`` joins every ``PATH`` entry -- relative or absolute --
    with the plain command name and, for a relative entry, only ever checks
    the result against the *calling process's* own current working
    directory; there is no parameter to override that. Some build tooling
    sets up a ``PATH`` with a relative entry (for example
    ``PATH=bin:/usr/bin``) meant to be read relative to the project being
    built, which can never be found this way for a command about to run
    from a different directory (``cwd``, the sandboxed copy of the
    repository) than the wrapper process's own cwd. This mirrors
    ``shutil.which``'s ``PATH``-splitting and executable-bit checks by hand,
    joining a relative entry with ``cwd`` instead of leaving it to resolve
    against ``os.getcwd()``; an absolute entry is used exactly as
    ``shutil.which`` would use it. A relative entry that, once joined with
    ``cwd``, would resolve outside ``sandbox_root`` is skipped without ever
    being checked against the real filesystem, so a ``PATH`` entry such as
    ``../../..`` cannot be used to probe for -- or resolve to -- executables
    on the host outside the sandboxed copy; it fails closed the same way an
    unresolvable command already does. ``PATH`` falls back to
    ``os.environ["PATH"]`` and then ``os.defpath``, matching
    ``shutil.which``'s own fallback for a caller that passes no ``PATH``.
    """
    search_path = path if path is not None else os.environ.get("PATH", os.defpath)
    if not search_path:
        return None
    for entry in search_path.split(os.pathsep):
        directory = Path(entry) if entry else cwd
        if not directory.is_absolute():
            directory = Path(os.path.normpath(cwd / directory))
            if not directory.is_relative_to(sandbox_root):
                continue
        candidate = directory / argv0
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _resolve_isolated_executable(
    argv0: str, *, cwd: Path, sandbox_root: Path, path: str | None
) -> Path | None:
    """Resolve ``argv0`` the way it will actually run inside the sandbox.

    ``shutil.which`` resolves any command string that contains a path
    separator (for example a repository launcher like ``./gradlew``)
    against the *calling process's* current working directory -- it never
    looks at an explicit ``cwd`` argument. That is correct for a bare
    command name looked up on ``PATH``, but wrong for a repository-local
    launcher: the wrapper process's own cwd is not the copied repository
    that will be mounted into the sandbox, so a perfectly valid
    ``./gradlew`` is resolved (or silently missed) against the wrong
    directory. When ``argv0`` names an explicit path -- it contains a
    directory component, whether relative or absolute -- it is resolved
    against ``cwd`` instead, matching where the command will actually be
    launched from once isolated. A bare name with no directory component
    keeps the original ``PATH``-search behavior via ``shutil.which`` first;
    ``shutil.which`` itself resolves a *relative* ``PATH`` entry only
    against the wrapper's own process cwd, so when it comes back empty this
    falls through to ``_which_relative_to_cwd``, which retries the search
    with relative ``PATH`` entries anchored at ``cwd`` instead -- covering
    build tooling that sets up a ``PATH`` meant to be read relative to the
    repository under test.
    """
    if os.path.dirname(argv0):
        candidate = Path(os.path.normpath(cwd / argv0))
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
        return None
    found = shutil.which(argv0, path=path)
    if found is not None:
        return Path(found)
    return _which_relative_to_cwd(argv0, cwd=cwd, sandbox_root=sandbox_root, path=path)


def isolated_command(
    command: str,
    *,
    backend: str,
    cwd: Path,
    sandbox_root: Path,
    env: dict[str, str],
) -> str:
    """Wrap one command in a read-only-root bubblewrap workspace.

    The command's executable must resolve on ``PATH``, as a repository-local
    path resolved against ``cwd``, or as a literal host path, and land
    inside the sandboxed workspace or the read-only bind roots. An
    executable that cannot be resolved is rejected rather than passed
    through unvalidated, so a lookup failure can never silently bypass the
    workspace/read-only-root check it was supposed to receive. An absolute
    executable path that resolves inside the sandbox copy is rewritten to
    its ``SANDBOX_MOUNT``-relative form: bubblewrap binds ``sandbox_root`` at
    ``SANDBOX_MOUNT``, not at its original host path, so the literal host
    absolute path this function validated against would not exist inside
    the sandbox and the command would fail to launch there unchanged.
    """
    argv = shlex.split(command)
    if not argv:
        raise ValueError("command must not be empty")
    bind_roots = _bind_roots()
    executable_path = _resolve_isolated_executable(
        argv[0], cwd=cwd, sandbox_root=sandbox_root, path=env.get("PATH")
    )
    if executable_path is None:
        raise RuntimeError(f"executable could not be resolved for isolation validation: {argv[0]}")
    if executable_path.is_relative_to(Path.home()):
        raise RuntimeError("commands from the host home directory are not allowed in isolation")
    if not (
        executable_path.is_relative_to(sandbox_root)
        or any(executable_path.is_relative_to(root) for root in bind_roots)
    ):
        raise RuntimeError(
            f"executable is outside the isolated bind roots: {executable_path}"
        )
    if Path(argv[0]).is_absolute() and executable_path.is_relative_to(sandbox_root):
        argv[0] = str(Path(SANDBOX_MOUNT) / executable_path.relative_to(sandbox_root))
    args = [backend, "--die-with-parent", "--new-session", "--unshare-pid", "--tmpfs", "/"]
    for root in bind_roots:
        args.extend(("--ro-bind", str(root), str(root)))
    for path in (
        "/etc/ssl",
        "/etc/hosts",
        "/etc/resolv.conf",
        "/etc/localtime",
        "/etc/passwd",
        "/etc/group",
        "/etc/nsswitch.conf",
    ):
        if Path(path).exists():
            args.extend(("--ro-bind", path, path))
    args.extend(
        (
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--bind",
            str(sandbox_root),
            SANDBOX_MOUNT,
            "--chdir",
            f"{SANDBOX_MOUNT}/{cwd.relative_to(sandbox_root)}",
            "--",
        )
    )
    return shlex.join([*args, *argv])


def start_service(label: str, command: str, cwd: Path, env: dict[str, str], logs_dir: Path) -> Service:
    """Start a service command in its own process group."""
    log_path = logs_dir / f"{label}.log"
    log_file = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        shlex.split(command),
        cwd=cwd,
        env=env,
        text=True,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        shell=False,
    )
    log_file.close()
    return Service(label=label, command=command, process=process, log_path=log_path)


def _require_loopback_ip_text(ip_text: str, hostname: str) -> None:
    """Reject a literal or resolved address that is not loopback."""
    try:
        address = ipaddress.ip_address(ip_text)
    except ValueError as exc:
        raise ValueError(f"URL cannot target external hostname: {hostname}") from exc
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if not address.is_loopback:
        raise ValueError(f"URL cannot target external hostname: {hostname}")


def _require_resolved_loopback_hostname(hostname: str) -> None:
    """Resolve a literal localhost name and require every answer to be loopback."""
    try:
        results = socket.getaddrinfo(hostname, None)
    except OSError as exc:
        raise ValueError(f"URL cannot target unresolved hostname: {hostname}") from exc
    if not results:
        raise ValueError(f"URL cannot target unresolved hostname: {hostname}")
    for result in results:
        _require_loopback_ip_text(result[4][0], hostname)


def require_loopback_readiness_url(url: str) -> None:
    """Reject a readiness URL that is not a local loopback HTTP(S) target.

    Operators should point ``--backend-ready-url`` and ``--frontend-ready-url``
    at the sandboxed service itself. Public hosts, cloud metadata addresses,
    unspecified bind addresses, DNS names other than literal ``localhost``,
    and userinfo-confused URLs are rejected before any request is opened.
    Literal ``localhost`` is resolved and every answer must be loopback, so a
    poisoned hosts file cannot smuggle a public A/AAAA record through the
    name allowlist. IPv4-mapped IPv6 addresses are unwrapped and re-checked
    so ``::ffff:8.8.8.8`` cannot bypass the loopback rule. A nonnumeric or
    out-of-range port is rejected here too, as the same ``ValueError`` class
    every other check in this function raises, so a malformed readiness URL
    fails with the documented invalid-readiness diagnostic instead of an
    uncaught exception once an HTTP client actually opens it.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError(f"URL must start with http:// or https://, got: {url}")
    if parsed.username or parsed.password:
        raise ValueError("URL cannot include userinfo")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"URL has a malformed port: {url}") from exc
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        raise ValueError("URL must include a loopback hostname")
    if hostname == "localhost":
        _require_resolved_loopback_hostname(hostname)
        return
    _require_loopback_ip_text(hostname, hostname)


def require_unoccupied_readiness_port(url: str) -> None:
    """Reject a readiness URL whose port already answers before this run starts a service.

    ``require_loopback_readiness_url`` only proves the URL targets loopback;
    it says nothing about *which* process on loopback will eventually answer
    it. ``isolated_command`` does not create a network namespace for the
    commands it wraps -- the backend, frontend, and E2E command all still
    need to reach the same host loopback interface the readiness poller
    itself uses (the poller runs unsandboxed, in this process), so giving the
    sandboxed commands a private network namespace is not an available
    option here without breaking that readiness/E2E flow. On a shared
    loopback interface, an operator- or config-supplied readiness URL that
    happens to name a port some other, unrelated process on the CI runner
    already occupies would otherwise be polled exactly like the real target:
    a response from that unrelated process reads as this run's service being
    ready, and any later request the E2E command makes to the same address
    reaches it too, whether or not it was ever meant to be reachable this
    way. Calling this once, immediately after ``require_loopback_readiness_url``
    and before ``start_service`` starts anything, ensures a port that
    answers now can only be attributed to some other process -- this run's
    own service cannot yet be listening -- so it is rejected here rather
    than trusted. A connection refusal or timeout means nothing is listening
    yet, which is the expected, accepted state before the service starts.
    """
    parsed = urllib.parse.urlparse(url)
    hostname = parsed.hostname or "127.0.0.1"
    port = parsed.port if parsed.port is not None else (443 if parsed.scheme.lower() == "https" else 80)
    try:
        with socket.create_connection((hostname, port), timeout=0.2):
            pass
    except OSError:
        return
    raise ValueError(
        f"readiness port is already in use by another process before this run started its service: {url}"
    )


def wait_for_url(url: str, timeout: int, service: Service) -> bool:
    """Poll a readiness URL until it responds or the service exits.

    The opener is built with an explicitly empty ``ProxyHandler({})`` so this
    loopback-only poll can never be routed through an ``HTTP_PROXY`` /
    ``HTTPS_PROXY`` / ``*_proxy`` environment variable. ``urllib.request``
    otherwise installs a default ``ProxyHandler`` (via ``getproxies()``) for
    every opener that does not already carry one, so a caller's process
    environment could silently forward this "loopback-only, isolated"
    readiness probe to an external proxy server, defeating the point of
    ``require_loopback_readiness_url``'s SSRF check below.
    """
    if not url:
        return True
    require_loopback_readiness_url(url)
    deadline = time.monotonic() + timeout
    opener = urllib.request.build_opener(NoRedirectHandler(), urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        if service.process.poll() is not None:
            return False
        try:
            with opener.open(url, timeout=2) as response:  # nosec B310
                if 200 <= response.status < 500:
                    return True
                time.sleep(1)
        except (urllib.error.URLError, TimeoutError):
            time.sleep(1)
    return False


def run_shell(command: str, cwd: Path, env: dict[str, str], timeout: int) -> subprocess.CompletedProcess[str]:
    """Run a shell command and capture its output."""
    return subprocess.run(
        shlex.split(command),
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        shell=False,
    )


def stop_service(service: Service) -> None:
    """Terminate a service process group and wait briefly for cleanup."""
    if service.process.poll() is not None:
        return
    try:
        os.killpg(service.process.pid, signal.SIGTERM)
        service.process.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(service.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        service.process.wait(timeout=10)


def tail_text(path: Path, max_lines: int = 80) -> str:
    """Return the final lines of a service log."""
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])


def emit_result(
    *,
    args: argparse.Namespace,
    copied_repo: Path,
    sandbox_root: Path,
    backend_ready: bool,
    frontend_ready: bool,
    exit_code: int,
    elapsed_seconds: float,
) -> None:
    """Print a machine-readable web E2E execution evidence summary."""
    payload = {
        "backend_cmd": args.backend_cmd,
        "backend_ready": backend_ready,
        "allowed_env": sorted(set(args.allow_env)),
        "cwd": str(copied_repo),
        "e2e_cmd": args.e2e_cmd,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "evidence_note": args.evidence_note,
        "exit_code": exit_code,
        "frontend_cmd": args.frontend_cmd,
        "frontend_ready": frontend_ready,
        "network": args.network,
        "isolation": args.isolation,
        "isolation_backend": getattr(args, "isolation_backend", "unknown"),
        "sandbox": str(sandbox_root) if args.keep_sandbox else "(removed)",
        "sandboxed": True,
    }
    print(f"{RESULT_MARKER} {json.dumps(payload, sort_keys=True)}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run backend, frontend, and E2E commands inside a sandbox copy."""
    args = parse_args(argv)
    sandbox = Path(tempfile.mkdtemp(prefix="sandboxed-web-e2e-"))
    copied_repo = sandbox / "repo"
    logs_dir = sandbox / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    services: list[Service] = []
    backend_ready = False
    frontend_ready = False
    exit_code = 1
    start = time.monotonic()
    try:
        try:
            copied_repo = sandboxed_verify.copy_workspace(Path(args.repo_root), sandbox, args.ignore)
        except ValueError as exc:
            print(f"sandboxed-web-e2e: workspace copy rejected: {exc}", file=sys.stderr)
            exit_code = 125
            return exit_code
        env = sandboxed_verify.scrubbed_env(sandbox, args.allow_env)
        try:
            backend = isolation_backend(args.isolation)
        except RuntimeError as exc:
            print(f"sandboxed-web-e2e: {exc}", file=sys.stderr)
            args.isolation_backend = "unavailable"
            exit_code = 126
            return exit_code
        args.isolation_backend = backend or "disabled"
        print(f"sandboxed-web-e2e: cwd={copied_repo}")
        if args.allow_env:
            print(f"sandboxed-web-e2e: allowed env names={','.join(sorted(set(args.allow_env)))}")
        if args.network != "default":
            print(f"sandboxed-web-e2e: network={args.network}")
        command_env = _sandbox_environment(env, sandbox) if backend else env
        try:
            backend_cmd = (
                isolated_command(
                    args.backend_cmd,
                    backend=backend,
                    cwd=copied_repo,
                    sandbox_root=sandbox,
                    env=env,
                )
                if backend
                else args.backend_cmd
            )
            frontend_cmd = (
                isolated_command(
                    args.frontend_cmd,
                    backend=backend,
                    cwd=copied_repo,
                    sandbox_root=sandbox,
                    env=env,
                )
                if backend
                else args.frontend_cmd
            )
            e2e_cmd = (
                isolated_command(
                    args.e2e_cmd,
                    backend=backend,
                    cwd=copied_repo,
                    sandbox_root=sandbox,
                    env=env,
                )
                if backend
                else args.e2e_cmd
            )
        except (RuntimeError, ValueError) as exc:
            print(f"sandboxed-web-e2e: isolation rejected command: {exc}", file=sys.stderr)
            exit_code = 126
            return exit_code
        try:
            if args.backend_ready_url:
                require_loopback_readiness_url(args.backend_ready_url)
                require_unoccupied_readiness_port(args.backend_ready_url)
            if args.frontend_ready_url:
                require_loopback_readiness_url(args.frontend_ready_url)
                require_unoccupied_readiness_port(args.frontend_ready_url)
        except ValueError as exc:
            print(f"sandboxed-web-e2e: invalid readiness URL: {exc}", file=sys.stderr)
            exit_code = 125
            return exit_code
        services.append(start_service("backend", backend_cmd, copied_repo, command_env, logs_dir))
        services.append(start_service("frontend", frontend_cmd, copied_repo, command_env, logs_dir))
        try:
            backend_ready = wait_for_url(args.backend_ready_url, args.startup_timeout, services[0])
            frontend_ready = wait_for_url(args.frontend_ready_url, args.startup_timeout, services[1])
        except ValueError as exc:
            print(f"sandboxed-web-e2e: invalid readiness URL: {exc}", file=sys.stderr)
            exit_code = 125
            return exit_code
        if not backend_ready or not frontend_ready:
            print("sandboxed-web-e2e: service readiness failed", file=sys.stderr)
            exit_code = 125
            return exit_code
        try:
            completed = run_shell(e2e_cmd, copied_repo, command_env, args.e2e_timeout)
            if completed.stdout:
                print(completed.stdout, end="")
            if completed.stderr:
                print(completed.stderr, end="", file=sys.stderr)
            exit_code = completed.returncode
            return exit_code
        except subprocess.TimeoutExpired as exc:
            stdout = sandboxed_verify.timeout_output_text(exc.stdout)
            stderr = sandboxed_verify.timeout_output_text(exc.stderr)
            if stdout:
                print(stdout, end="" if stdout.endswith("\n") else "\n")
            if stderr:
                print(stderr, end="" if stderr.endswith("\n") else "\n", file=sys.stderr)
            print(f"sandboxed-web-e2e: e2e command timed out after {args.e2e_timeout}s", file=sys.stderr)
            exit_code = 124
            return exit_code
    finally:
        for service in reversed(services):
            stop_service(service)
            log_tail = tail_text(service.log_path)
            if log_tail:
                print(f"--- {service.label} log tail ---")
                print(log_tail)
        emit_result(
            args=args,
            copied_repo=copied_repo,
            sandbox_root=sandbox,
            backend_ready=backend_ready,
            frontend_ready=frontend_ready,
            exit_code=exit_code,
            elapsed_seconds=time.monotonic() - start,
        )
        if not args.keep_sandbox:
            shutil.rmtree(sandbox, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
