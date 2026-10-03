"""Behavioral regression for transient trusted-archive download failures."""

from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_ROOT = REPOSITORY_ROOT / ".github" / "workflows"
WORKFLOWS = (
    "noema-review.yml",
    "opencode-review.yml",
    "pr-review-merge-scheduler.yml",
)


class TransientArchiveHandler(BaseHTTPRequestHandler):
    """Return one transient 502 response before a successful archive body."""

    request_count = 0

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        """Serve the deterministic failure-then-success sequence."""
        type(self).request_count += 1
        if type(self).request_count == 1:
            self.send_response(502)
            self.end_headers()
            return
        body = b"trusted-archive"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """Keep the regression output focused on assertion failures."""


def archive_command(workflow_path: Path) -> str:
    """Extract archive assignments plus the production curl command."""
    lines = workflow_path.read_text(encoding="utf-8").splitlines()
    start = next(
        index for index, line in enumerate(lines) if "trusted_archive=" in line
    )
    stop = next(
        index
        for index in range(start, len(lines))
        if "TRUSTED_SOURCE_REF}" in lines[index]
    )
    return textwrap.dedent("\n".join(lines[start : stop + 1]))


@pytest.mark.parametrize("workflow_name", WORKFLOWS)
def test_trusted_archive_download_retries_transient_502(workflow_name: str) -> None:
    """The production curl command must survive one transient GitHub 502."""
    TransientArchiveHandler.request_count = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), TransientArchiveHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            environment = os.environ | {
                "GH_TOKEN": "test-token",
                "GITHUB_API_URL": f"http://127.0.0.1:{server.server_port}",
                "GITHUB_WORKSPACE": temporary_directory,
                "RUNNER_TEMP": temporary_directory,
                "TRUSTED_SOURCE_REF": "1" * 40,
            }
            result = subprocess.run(
                [
                    "bash",
                    "-euo",
                    "pipefail",
                    "-c",
                    archive_command(WORKFLOW_ROOT / workflow_name),
                ],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, result.stderr
            assert TransientArchiveHandler.request_count == 2
            archive_path = next(temporary_path.glob("trusted-*.tar.gz"))
            assert archive_path.read_bytes() == b"trusted-archive"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
