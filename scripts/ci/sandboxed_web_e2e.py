"""Run backend, frontend, and E2E commands in an isolated workspace."""

from __future__ import annotations

import argparse
import json
import os
import signal
import shutil
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


def start_service(label: str, command: str, cwd: Path, env: dict[str, str], logs_dir: Path) -> Service:
    """Start a service command in its own process group."""
    log_path = logs_dir / f"{label}.log"
    log_file = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(  # nosec B602 - command must run in a shell by definition
        command,
        cwd=cwd,
        env=env,
        shell=True,
        executable="/bin/bash",
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
    while time.monotonic() < deadline:
        if service.process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=2) as response:  # nosec B310
                if 200 <= response.status < 500:
                    return True
        except (urllib.error.URLError, TimeoutError):
            time.sleep(1)
    return False


def run_shell(command: str, cwd: Path, env: dict[str, str], timeout: int) -> subprocess.CompletedProcess[str]:
    """Run a shell command and capture its output."""
    return subprocess.run(  # nosec B602 - command must run in a shell by definition
        command,
        cwd=cwd,
        env=env,
        shell=True,
        executable="/bin/bash",
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
        print(f"sandboxed-web-e2e: cwd={copied_repo}")
        if args.allow_env:
            print(f"sandboxed-web-e2e: allowed env names={','.join(sorted(set(args.allow_env)))}")
        if args.network != "default":
            print(f"sandboxed-web-e2e: network={args.network}")
        services.append(start_service("backend", args.backend_cmd, copied_repo, env, logs_dir))
        services.append(start_service("frontend", args.frontend_cmd, copied_repo, env, logs_dir))
        backend_ready = wait_for_url(args.backend_ready_url, args.startup_timeout, services[0])
        frontend_ready = wait_for_url(args.frontend_ready_url, args.startup_timeout, services[1])
        if not backend_ready or not frontend_ready:
            print("sandboxed-web-e2e: service readiness failed", file=sys.stderr)
            exit_code = 125
            return exit_code
        try:
            completed = run_shell(args.e2e_cmd, copied_repo, env, args.e2e_timeout)
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
