"""Regression seam for PostgreSQL startup paths containing spaces."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shlex
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/ci/law_ai_agent_ci.sh"


def _run_pg_ctl_fragment(tmp_path: Path) -> list[str]:
    """Execute the exact pg_ctl invocation from the production helper."""
    source = HELPER.read_text()
    match = re.search(
        r"(?m)^  (\"\$pg_bin/pg_ctl\".*?)(?=^  \"\$pg_bin/createdb\")",
        source,
        re.S,
    )
    assert match, "production pg_ctl invocation not found"
    pg_bin = tmp_path / "bin"
    pg_bin.mkdir()
    capture = tmp_path / "argv.json"
    (pg_bin / "pg_ctl").write_text(
        "#!/bin/sh\n"
        "python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "
        f'"$@" > {shlex.quote(str(capture))}\n'
    )
    (pg_bin / "pg_ctl").chmod(0o700)
    private = tmp_path / "runner temp" / "lawci.data" / "private" / "postgres"
    private.mkdir(parents=True)
    script = textwrap.dedent(
        f"""
        set -eu
        pg_bin={shlex.quote(str(pg_bin))}
        private={shlex.quote(str(private))}
        LAW_AGENT_POSTGRES_PORT=55439
        scratch={shlex.quote(str(tmp_path / 'runner temp' / 'lawci.data'))}
        {textwrap.dedent(match.group(1))}
        """
    )
    result = subprocess.run(["bash", "-eu", "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(capture.read_text())


def test_pg_ctl_preserves_spaced_socket_path(tmp_path):
    """The server option parser receives one complete socket path token."""
    argv = _run_pg_ctl_fragment(tmp_path)
    payload = argv[argv.index("-o") + 1]
    parsed = shlex.split(payload)
    assert parsed[parsed.index("-k") + 1] == str(tmp_path / "runner temp" / "lawci.data" / "private" / "postgres" / "socket")


def test_libpq_conninfo_preserves_spaced_socket_path(tmp_path):
    """The consumer conninfo parser receives one complete host value."""
    source = HELPER.read_text()
    line = next(line.strip() for line in source.splitlines() if "LAW_AGENT_TEST_DATABASE_URL=" in line)
    private = tmp_path / "runner temp" / "lawci.data" / "private" / "postgres"
    script = textwrap.dedent(
        f"""
        set -eu
        private={shlex.quote(str(private))}
        LAW_AGENT_POSTGRES_USER=runner
        LAW_AGENT_POSTGRES_PORT=55439
        {line}
        printf '%s' "$LAW_AGENT_TEST_DATABASE_URL"
        """
    )
    result = subprocess.run(["bash", "-eu", "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    fields = shlex.split(result.stdout)
    assert fields[fields.index("port=55439") - 1] == "host=" + str(private / "socket")
