"""Run backend, frontend, and E2E commands in an isolated workspace."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
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
from typing import BinaryIO

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.ci import bounded_subprocess, sandboxed_verify


RESULT_MARKER = "SANDBOXED_WEB_E2E_RESULT"
DEFAULT_TAIL_BYTES = 65_536


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Explicitly disable redirects to prevent SSRF bypasses via 301/302 to local IPs."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Raise an HTTPError instead of following the redirect."""
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


@dataclass
class Service:
    """A long-running web service process and its bounded combined log capture."""

    label: str
    command: str
    process: subprocess.Popen[bytes]
    log_path: Path
    capture: bounded_subprocess.BoundedOutputCapture | None = None
    log_limit_bytes: int = bounded_subprocess.DEFAULT_SERVICE_LOG_LIMIT_BYTES


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
    parser.add_argument(
        "--output-limit-bytes",
        type=int,
        default=bounded_subprocess.DEFAULT_COMMAND_OUTPUT_LIMIT_BYTES,
        help="Maximum retained stdout and stderr bytes for the E2E command.",
    )
    parser.add_argument(
        "--service-log-limit-bytes",
        type=int,
        default=bounded_subprocess.DEFAULT_SERVICE_LOG_LIMIT_BYTES,
        help="Maximum retained combined log bytes for each long-running service.",
    )
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
    try:
        args.output_limit_bytes = bounded_subprocess.validate_output_limit(
            args.output_limit_bytes,
            "--output-limit-bytes",
        )
        args.service_log_limit_bytes = bounded_subprocess.validate_output_limit(
            args.service_log_limit_bytes,
            "--service-log-limit-bytes",
        )
    except ValueError as error:
        parser.error(str(error))
    for name in args.allow_env:
        if not sandboxed_verify.ENV_NAME_RE.match(name):
            parser.error(f"--allow-env must be an environment variable name: {name}")
    return args


def _cleanup_failed_service_start(
    process: subprocess.Popen[bytes],
    stream: BinaryIO,
) -> None:
    """Best-effort stop, reap, and close after bounded capture startup fails."""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        bounded_subprocess.kill_process_group(process)
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        process.wait(timeout=10)
    with contextlib.suppress(OSError):
        stream.close()


def start_service(
    label: str,
    command: str,
    cwd: Path,
    env: dict[str, str],
    logs_dir: Path,
    log_limit_bytes: int = bounded_subprocess.DEFAULT_SERVICE_LOG_LIMIT_BYTES,
) -> Service:
    """Start one service group and continuously drain its combined bounded log."""
    bounded_subprocess.require_supported_platform()
    log_limit = bounded_subprocess.validate_output_limit(
        log_limit_bytes,
        "service log limit",
    )
    log_path = logs_dir / f"{label}.log"
    process = subprocess.Popen(
        shlex.split(command),
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        start_new_session=True,
        shell=False,
    )
    if process.stdout is None:
        bounded_subprocess.kill_process_group(process)
        process.wait()
        raise RuntimeError("service output pipe was not created")
    try:
        capture = bounded_subprocess.start_bounded_capture(
            process.stdout,
            evidence_limit_bytes=log_limit,
            on_limit=lambda: bounded_subprocess.kill_process_group(process),
            destination=log_path,
        )
    except BaseException:
        _cleanup_failed_service_start(process, process.stdout)
        raise
    return Service(
        label=label,
        command=command,
        process=process,
        log_path=log_path,
        capture=capture,
        log_limit_bytes=log_limit,
    )


def service_output_limited(service: Service) -> bool:
    """Return whether one service exceeded its declared combined log budget."""
    if service.capture is not None:
        return service.capture.output_limited
    return (
        service.log_path.exists()
        and service.log_path.stat().st_size > service.log_limit_bytes
    )


def wait_for_url(url: str, timeout: int, service: Service) -> bool:
    """Poll a readiness URL until it responds, exits, or exceeds its log budget."""
    if not url:
        return True
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError(f"URL must start with http:// or https://, got: {url}")
    deadline = time.monotonic() + timeout
    opener = urllib.request.build_opener(NoRedirectHandler())
    while time.monotonic() < deadline:
        if service_output_limited(service) or service.process.poll() is not None:
            return False
        try:
            with opener.open(url, timeout=2) as response:  # nosec B310
                if 200 <= response.status < 500:
                    return True
        except (urllib.error.URLError, TimeoutError):
            time.sleep(1)
    return False


def run_shell(
    command: str,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    output_limit_bytes: int = bounded_subprocess.DEFAULT_COMMAND_OUTPUT_LIMIT_BYTES,
) -> bounded_subprocess.BoundedCompletedProcess:
    """Run one shell-style command without a shell and with bounded pipe drains."""
    return bounded_subprocess.run_bounded_command(
        shlex.split(command),
        cwd=cwd,
        env=env,
        timeout=timeout,
        evidence_limit_bytes=output_limit_bytes,
    )


def stop_service(service: Service) -> None:
    """Terminate a service process group and finalize its bounded log evidence."""
    if service.process.poll() is None:
        try:
            os.killpg(service.process.pid, signal.SIGTERM)
            service.process.wait(timeout=10)
        except ProcessLookupError:
            pass
        except subprocess.TimeoutExpired:
            bounded_subprocess.kill_process_group(service.process)
            service.process.wait(timeout=10)
    if service.capture is not None:
        service.capture.join(timeout=10)


def tail_text(
    path: Path,
    max_lines: int = 80,
    max_bytes: int = DEFAULT_TAIL_BYTES,
) -> str:
    """Return final lines after a byte-bounded service evidence read."""
    if max_lines <= 0:
        raise ValueError("max_lines must be positive")
    if not path.exists():
        return ""
    bounded_text = bounded_subprocess.read_bounded_suffix(path, max_bytes)
    lines = bounded_text.text.splitlines()
    tail = "\n".join(lines[-max_lines:])
    if bounded_text.truncated and bounded_subprocess.TRUNCATION_MARKER.strip() not in tail:
        return f"{bounded_subprocess.TRUNCATION_MARKER.strip()}\n{tail}"
    return tail


def emit_result(
    *,
    args: argparse.Namespace,
    copied_repo: Path,
    sandbox_root: Path,
    backend_ready: bool,
    frontend_ready: bool,
    exit_code: int,
    elapsed_seconds: float,
    output_limited: bool,
    output_limit_unsupported: bool,
    service_capture_failed: bool,
    path_boundary_rejected: bool = False,
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
        "output_limit_bytes": args.output_limit_bytes,
        "output_limited": output_limited,
        "output_limit_unsupported": output_limit_unsupported,
        "path_boundary_rejected": path_boundary_rejected,
        "sandbox": str(sandbox_root) if args.keep_sandbox else "(removed)",
        "sandboxed": True,
        "service_capture_failed": service_capture_failed,
        "service_log_limit_bytes": args.service_log_limit_bytes,
    }
    print()
    print(f"{RESULT_MARKER} {json.dumps(payload, sort_keys=True)}")


def _services_output_limited(services: Sequence[Service]) -> bool:
    """Return whether any started service exceeded its combined log budget."""
    return any(service_output_limited(service) for service in services)


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
    output_limited = False
    output_limit_unsupported = False
    service_capture_failed = False
    service_limit_reported = False
    path_boundary_rejected = False
    start = time.monotonic()
    try:
        try:
            copied_repo = sandboxed_verify.copy_workspace(Path(args.repo_root), sandbox, args.ignore)
            env = sandboxed_verify.scrubbed_env(sandbox, args.allow_env)
            print(f"sandboxed-web-e2e: cwd={copied_repo}")
            if args.allow_env:
                print(f"sandboxed-web-e2e: allowed env names={','.join(sorted(set(args.allow_env)))}")
            if args.network != "default":
                print(f"sandboxed-web-e2e: network={args.network}")
            services.append(
                start_service(
                    "backend",
                    args.backend_cmd,
                    copied_repo,
                    env,
                    logs_dir,
                    args.service_log_limit_bytes,
                )
            )
            services.append(
                start_service(
                    "frontend",
                    args.frontend_cmd,
                    copied_repo,
                    env,
                    logs_dir,
                    args.service_log_limit_bytes,
                )
            )
            backend_ready = wait_for_url(args.backend_ready_url, args.startup_timeout, services[0])
            frontend_ready = wait_for_url(args.frontend_ready_url, args.startup_timeout, services[1])
            if _services_output_limited(services):
                output_limited = True
                service_limit_reported = True
                print(
                    "sandboxed-web-e2e: service output exceeded "
                    f"{args.service_log_limit_bytes} bytes",
                    file=sys.stderr,
                )
                exit_code = bounded_subprocess.OUTPUT_LIMIT_EXIT_CODE
            elif not backend_ready or not frontend_ready:
                print("sandboxed-web-e2e: service readiness failed", file=sys.stderr)
                exit_code = 125
            else:
                try:
                    completed = run_shell(
                        args.e2e_cmd,
                        copied_repo,
                        env,
                        args.e2e_timeout,
                        args.output_limit_bytes,
                    )
                    if completed.stdout:
                        print(completed.stdout, end="")
                    if completed.stderr:
                        print(completed.stderr, end="", file=sys.stderr)
                    output_limited = bool(getattr(completed, "output_limited", False))
                    if output_limited:
                        print(
                            "sandboxed-web-e2e: E2E output exceeded "
                            f"{args.output_limit_bytes} bytes",
                            file=sys.stderr,
                        )
                        exit_code = bounded_subprocess.OUTPUT_LIMIT_EXIT_CODE
                    else:
                        exit_code = completed.returncode
                except subprocess.TimeoutExpired as exc:
                    stdout = sandboxed_verify.timeout_output_text(exc.stdout)
                    stderr = sandboxed_verify.timeout_output_text(exc.stderr)
                    if stdout:
                        print(stdout, end="" if stdout.endswith("\n") else "\n")
                    if stderr:
                        print(stderr, end="" if stderr.endswith("\n") else "\n", file=sys.stderr)
                    output_limited = bool(getattr(exc, "output_limited", False))
                    print(f"sandboxed-web-e2e: e2e command timed out after {args.e2e_timeout}s", file=sys.stderr)
                    exit_code = 124
        except bounded_subprocess.OutputLimitUnsupportedError:
            output_limit_unsupported = True
            print(
                "sandboxed-web-e2e: bounded child output is unavailable on this platform",
                file=sys.stderr,
            )
            exit_code = bounded_subprocess.OUTPUT_LIMIT_EXIT_CODE
        except sandboxed_verify.RepositoryPathBoundaryError:
            path_boundary_rejected = True
            copied_repo = Path("(not-created)")
            print(
                "sandboxed-web-e2e: repository path boundary rejected",
                file=sys.stderr,
            )
            exit_code = sandboxed_verify.PATH_BOUNDARY_EXIT_CODE
        except sandboxed_verify.RepositoryRootError:
            copied_repo = Path("(not-created)")
            print(
                "sandboxed-web-e2e: repository root is not a directory",
                file=sys.stderr,
            )
            exit_code = 1
        except RuntimeError:
            print(
                "sandboxed-web-e2e: bounded output capture failed",
                file=sys.stderr,
            )
            exit_code = bounded_subprocess.OUTPUT_LIMIT_EXIT_CODE
    finally:
        for service in reversed(services):
            try:
                stop_service(service)
            except (OSError, RuntimeError, subprocess.SubprocessError):
                with contextlib.suppress(OSError, subprocess.SubprocessError):
                    bounded_subprocess.kill_process_group(service.process)
                with contextlib.suppress(OSError, subprocess.SubprocessError):
                    wait = getattr(service.process, "wait", None)
                    if wait is not None:
                        wait(timeout=10)
                if service.capture is not None:
                    with contextlib.suppress(OSError, RuntimeError, subprocess.SubprocessError):
                        service.capture.join(timeout=10)
                service_capture_failed = True
                if exit_code == 0:
                    exit_code = bounded_subprocess.OUTPUT_LIMIT_EXIT_CODE
                print(
                    "sandboxed-web-e2e: bounded service capture failed",
                    file=sys.stderr,
                )
        if _services_output_limited(services):
            output_limited = True
            if exit_code == 0:
                exit_code = bounded_subprocess.OUTPUT_LIMIT_EXIT_CODE
            if not service_limit_reported:
                print(
                    "sandboxed-web-e2e: service output exceeded "
                    f"{args.service_log_limit_bytes} bytes",
                    file=sys.stderr,
                )
        for service in reversed(services):
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
            output_limited=output_limited,
            output_limit_unsupported=output_limit_unsupported,
            service_capture_failed=service_capture_failed,
            path_boundary_rejected=path_boundary_rejected,
        )
        if not args.keep_sandbox:
            shutil.rmtree(sandbox, ignore_errors=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
