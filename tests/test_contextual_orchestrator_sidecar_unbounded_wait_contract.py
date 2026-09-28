"""Semantic regression tests for the review-sidecar unbounded-wait contract."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SIDECAR = _REPO_ROOT / "scripts/ci/contextual_orchestrator_review_sidecar.sh"
_CURL_TIMEOUT_OPTION = re.compile(
    r"(?:--connect-timeout(?:=|\s)|--max-time(?:=|\s)|(?:^|\s)-m(?:=|\s|[0-9]))",
    re.MULTILINE,
)
_FINITE_WAIT_GUARD = re.compile(
    r"(?:\b(?:attempt|attempts|retry|retries|poll|polls|deadline|timeout|elapsed|i)\b[^\n]*"
    r"(?:-ge|-gt|>=|>|-le|-lt|<=|<))",
    re.IGNORECASE,
)


def _shell_command_containing(script: str, marker: str) -> str:
    """Return the shell command that contains ``marker``, including continuations."""
    lines = script.splitlines()
    marker_index = next(index for index, line in enumerate(lines) if marker in line)
    start = marker_index
    while start > 0 and lines[start - 1].rstrip().endswith("\\"):
        start -= 1
    while start > 0 and "curl " not in lines[start] and "curl" not in lines[start]:
        start -= 1
    end = marker_index
    while end < len(lines) - 1 and lines[end].rstrip().endswith("\\"):
        end += 1
    command = "\n".join(lines[start : end + 1])
    assert "curl" in command
    return command


def _health_poll_block(script: str) -> str:
    """Return the complete healthz polling loop, from ``until`` through ``done``."""
    match = re.search(
        r"(?ms)^until curl[^\n]*?/healthz[^\n]*; do\n(?P<body>.*?)^done$",
        script,
    )
    assert match is not None, "sidecar must retain an explicit healthz polling loop"
    return match.group(0)


def test_discovery_and_health_curl_commands_have_no_wall_clock_timeout_options() -> None:
    """Every discovery/health curl must remain free of finite curl timeout options."""
    script = _SIDECAR.read_text(encoding="utf-8")
    commands = (
        _shell_command_containing(script, "https://openrouter.ai/api/v1/endpoints/zdr"),
        _shell_command_containing(
            script,
            'http://${ORCHESTRATOR_HOST}:${ORCHESTRATOR_PORT}/healthz',
        ),
    )

    for command in commands:
        assert _CURL_TIMEOUT_OPTION.search(command) is None, command


def test_health_polling_has_no_attempt_or_elapsed_deadline() -> None:
    """Health polling may fail on sidecar exit, but never on a local time/attempt budget."""
    script = _SIDECAR.read_text(encoding="utf-8")
    block = _health_poll_block(script)

    assert _FINITE_WAIT_GUARD.search(block) is None, block
    assert "SIDECAR_READINESS_TIMEOUT" not in block
    assert "READINESS_DEADLINE" not in block
    assert "timeout_seconds" not in block.casefold()
    assert 'kill -0 "$sidecar_pid"' in block
    assert 'fail "sidecar exited before healthz' in block


def test_health_wait_reports_completed_stages_without_reading_report_content(tmp_path: Path) -> None:
    """Pending startup remains observable without exposing provider report content."""
    block = _health_poll_block(_SIDECAR.read_text(encoding="utf-8"))
    for states in ((False,) * 4, (True, True, False, False), (True,) * 4):
        reports = [tmp_path / f"report-{index}.json" for index in range(4)]
        for report, present in zip(reports, states):
            if present:
                report.write_text('{"credential":"DO_NOT_PRINT"}')
            else:
                report.unlink(missing_ok=True)
        script = r'''
set -eu
i=0
calls=0
sidecar_pid=$$
ORCHESTRATOR_HOST=127.0.0.1
ORCHESTRATOR_PORT=18080
discovery_report=$1
catalog_file=$2
policy_report=$3
preflight_report=$4
curl() { calls=$((calls + 1)); [ "$calls" -gt 60 ]; }
sleep() { :; }
log() { printf '%s\n' "$*"; }
''' + block
        result = subprocess.run(
            ["bash", "-c", script, "startup-test", *map(str, reports)],
            capture_output=True, text=True, timeout=5, check=False,
        )
        assert result.returncode == 0, result.stderr
        discovery, catalog, policy, preflight = (
            "present" if present else "absent" for present in states
        )
        assert result.stdout == (
            f"startup pending: polls=60 discovery={discovery} catalog={catalog} "
            f"policy={policy} preflight={preflight}\n"
        )
        assert "DO_NOT_PRINT" not in result.stdout + result.stderr
