"""Run backend, frontend, and E2E commands in an isolated workspace."""

from __future__ import annotations

import argparse
import json
import os
import platform
import signal
import shutil
import shlex
import subprocess
import sys
import tempfile
import time
import urllib.error
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
    return args


def isolation_backend(mode: str) -> str | None:
    """Resolve the requested OS isolation backend without silently downgrading."""
    if mode == "disabled":
        return None
    if platform.system() != "Linux":
        raise RuntimeError("required isolation is only supported on Linux with bubblewrap")
    backend = shutil.which("bwrap")
    if backend is None:
        raise RuntimeError("required isolation needs bubblewrap (bwrap) on PATH")
    return backend


def _sandbox_environment(env: dict[str, str], sandbox_root: Path) -> dict[str, str]:
    """Map host sandbox paths to the path exposed inside the bubblewrap mount."""
    source = str(sandbox_root)
    mapped = dict(env)
    for key in ("HOME", "TMPDIR", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
        value = mapped.get(key)
        if value:
            mapped[key] = value.replace(source, SANDBOX_MOUNT, 1)
    return mapped


def isolated_command(
    command: str,
    *,
    backend: str,
    cwd: Path,
    sandbox_root: Path,
    env: dict[str, str],
) -> str:
    """Wrap one command in a read-only-root bubblewrap workspace."""
    argv = shlex.split(command)
    if not argv:
        raise ValueError("command must not be empty")
    executable = shutil.which(argv[0], path=env.get("PATH"))
    if executable is not None and Path(executable).is_relative_to(Path.home()):
        raise RuntimeError("commands from the host home directory are not allowed in isolation")
    bind_roots = [Path(path) for path in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/opt") if Path(path).exists()]
    args = [backend, "--die-with-parent", "--new-session", "--unshare-pid"]
    for root in bind_roots:
        args.extend(("--ro-bind", str(root), str(root)))
    for path in ("/etc/ssl", "/etc/hosts", "/etc/resolv.conf", "/etc/localtime"):
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
    )
    log_file.close()
    return Service(label=label, command=command, process=process, log_path=log_path)


def wait_for_url(url: str, timeout: int, service: Service) -> bool:
    """Poll a readiness URL until it responds or the service exits."""
    if not url:
        return True
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError(f"URL must start with http:// or https://, got: {url}")
    deadline = time.monotonic() + timeout
    opener = urllib.request.build_opener(NoRedirectHandler())
    while time.monotonic() < deadline:
        if service.process.poll() is not None:
            return False
        try:
            with opener.open(url, timeout=2) as response:  # nosec B310
                if 200 <= response.status < 500:
                    return True
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
        copied_repo = sandboxed_verify.copy_workspace(Path(args.repo_root), sandbox, args.ignore)
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
        services.append(start_service("backend", backend_cmd, copied_repo, command_env, logs_dir))
        services.append(start_service("frontend", frontend_cmd, copied_repo, command_env, logs_dir))
        backend_ready = wait_for_url(args.backend_ready_url, args.startup_timeout, services[0])
        frontend_ready = wait_for_url(args.frontend_ready_url, args.startup_timeout, services[1])
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
