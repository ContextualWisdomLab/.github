"""Executable contracts for the Orca GitHub token bootstrap."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT_PATH = Path("scripts/orca/export_github_token.sh")
APP_TOKEN = "synthetic-app-token-sentinel"
PAT_TOKEN = "synthetic-pat-token-sentinel"


def _write_executable(script_path: Path, script_body: str) -> None:
    """Write one executable test double."""
    script_path.write_text(script_body, encoding="utf-8")
    script_path.chmod(0o700)


def _test_environment(tmp_path: Path, *, http_status: str = "200") -> tuple[dict[str, str], Path]:
    """Return an isolated worker environment with deterministic curl and sleep."""
    worker_dir = tmp_path / "workers"
    fake_bin_dir = tmp_path / "bin"
    worker_dir.mkdir()
    fake_bin_dir.mkdir()
    curl_args_path = tmp_path / "curl-args.bin"
    sleep_args_path = tmp_path / "sleep-args.txt"
    _write_executable(
        fake_bin_dir / "curl",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\0' "$@" >"${FAKE_CURL_ARGS_PATH}"
header_path=""
while [[ "$#" -gt 0 ]]; do
  if [[ "$1" == "-D" ]]; then
    header_path="$2"
    shift 2
  else
    shift
  fi
done
printf 'HTTP/1.1 %s\\r\\nX-RateLimit-Remaining: 100\\r\\nX-RateLimit-Reset: 4102444800\\r\\nX-RateLimit-Resource: core\\r\\n\\r\\n' "${FAKE_CURL_STATUS}" >"${header_path}"
printf '%s' "${FAKE_CURL_STATUS}"
""",
    )
    _write_executable(
        fake_bin_dir / "sleep",
        """#!/usr/bin/env bash
printf '%s\\n' "$*" >"${FAKE_SLEEP_ARGS_PATH}"
""",
    )
    child_token_path = tmp_path / "child-token.txt"
    environment = os.environ.copy()
    environment.update(
        {
            "ORCA_WORKERS_DIR": str(worker_dir),
            "PATH": f"{fake_bin_dir}{os.pathsep}{environment['PATH']}",
            "FAKE_CURL_ARGS_PATH": str(curl_args_path),
            "FAKE_CURL_STATUS": http_status,
            "FAKE_SLEEP_ARGS_PATH": str(sleep_args_path),
            "CHILD_TOKEN_PATH": str(child_token_path),
        }
    )
    return environment, child_token_path


def _run_bootstrap(environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the bootstrap and capture the child process token without printing it."""
    child_code = (
        "import os; from pathlib import Path; "
        "Path(os.environ['CHILD_TOKEN_PATH']).write_text(os.environ['GH_TOKEN'])"
    )
    return subprocess.run(
        ["bash", str(SCRIPT_PATH), "--", sys.executable, "-c", child_code],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


@pytest.mark.parametrize(
    "metadata_text",
    [None, "not-json", "{}", '{"expires_at":"not-a-date"}'],
)
def test_untrusted_app_metadata_falls_back_before_any_probe(
    tmp_path: Path,
    metadata_text: str | None,
) -> None:
    """Missing or malformed expiry evidence cannot authorize an App token."""
    environment, child_token_path = _test_environment(tmp_path)
    worker_dir = Path(environment["ORCA_WORKERS_DIR"])
    (worker_dir / "gh-token-app").write_text(APP_TOKEN, encoding="utf-8")
    (worker_dir / "gh-token").write_text(PAT_TOKEN, encoding="utf-8")
    if metadata_text is not None:
        (worker_dir / "gh-token-app.meta.json").write_text(metadata_text, encoding="utf-8")

    completed_process = _run_bootstrap(environment)

    assert completed_process.returncode == 0, completed_process.stderr
    assert child_token_path.read_text(encoding="utf-8") == PAT_TOKEN
    rate_limit = json.loads((worker_dir / "rate-limit.json").read_text(encoding="utf-8"))
    assert rate_limit["source"] == "pat"


@pytest.mark.parametrize(
    ("expires_at", "expected_token", "expected_source"),
    [
        ("2999-01-01T00:00:00Z", APP_TOKEN, "app"),
        ("2000-01-01T00:00:00Z", PAT_TOKEN, "pat"),
    ],
)
def test_trusted_expiry_selects_the_expected_token(
    tmp_path: Path,
    expires_at: str,
    expected_token: str,
    expected_source: str,
) -> None:
    """Only a parseable future expiry selects the preferred App token."""
    environment, child_token_path = _test_environment(tmp_path)
    worker_dir = Path(environment["ORCA_WORKERS_DIR"])
    (worker_dir / "gh-token-app").write_text(APP_TOKEN, encoding="utf-8")
    (worker_dir / "gh-token").write_text(PAT_TOKEN, encoding="utf-8")
    (worker_dir / "gh-token-app.meta.json").write_text(
        json.dumps({"expires_at": expires_at}),
        encoding="utf-8",
    )

    completed_process = _run_bootstrap(environment)

    assert completed_process.returncode == 0, completed_process.stderr
    assert child_token_path.read_text(encoding="utf-8") == expected_token
    rate_limit = json.loads((worker_dir / "rate-limit.json").read_text(encoding="utf-8"))
    assert rate_limit["source"] == expected_source


def test_probe_never_places_the_selected_token_in_curl_argv(tmp_path: Path) -> None:
    """Authorization material reaches curl through a protected file, not argv."""
    environment, _child_token_path = _test_environment(tmp_path)
    worker_dir = Path(environment["ORCA_WORKERS_DIR"])
    (worker_dir / "gh-token-app").write_text(APP_TOKEN, encoding="utf-8")
    (worker_dir / "gh-token-app.meta.json").write_text(
        '{"expires_at":"2999-01-01T00:00:00Z"}',
        encoding="utf-8",
    )

    completed_process = _run_bootstrap(environment)

    assert completed_process.returncode == 0, completed_process.stderr
    curl_arguments = Path(environment["FAKE_CURL_ARGS_PATH"]).read_bytes()
    assert APP_TOKEN.encode() not in curl_arguments
    assert PAT_TOKEN.encode() not in curl_arguments


@pytest.mark.parametrize("http_status", ["403", "429"])
def test_rate_limit_records_state_and_returns_without_sleeping(
    tmp_path: Path,
    http_status: str,
) -> None:
    """A rate-limit response records one probe and returns control immediately."""
    environment, _child_token_path = _test_environment(tmp_path, http_status=http_status)
    worker_dir = Path(environment["ORCA_WORKERS_DIR"])
    (worker_dir / "gh-token").write_text(PAT_TOKEN, encoding="utf-8")

    completed_process = _run_bootstrap(environment)

    assert completed_process.returncode != 0
    assert not Path(environment["FAKE_SLEEP_ARGS_PATH"]).exists()
    rate_limit = json.loads((worker_dir / "rate-limit.json").read_text(encoding="utf-8"))
    assert rate_limit["remaining"] == 100
    assert rate_limit["source"] == "pat"
