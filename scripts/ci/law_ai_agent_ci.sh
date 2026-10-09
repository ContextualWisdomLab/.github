#!/usr/bin/env bash
# Law CI: isolate the consumer, native test database, tool cache and built artifacts.
# Shell function comments are the docstring contract; Python blocks use docstrings.
set -euo pipefail
SELF="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/$(basename -- "${BASH_SOURCE[0]}")"

# Verify pytest's JUnit evidence, including every nested suite and executed count.
verify_junit() {
  python3 - "$1" <<'PY'
"""Reject skips, failures, errors and empty JUnit evidence."""
import sys
import xml.etree.ElementTree as ET
suites = list(ET.parse(sys.argv[1]).getroot().iter("testsuite"))
valid = bool(suites) and sum(int(s.get("tests", "0")) for s in suites) > 0
valid &= all(int(s.get(k, "0")) == 0 for s in suites for k in ("skipped", "failures", "errors"))
valid &= not any(ET.parse(sys.argv[1]).getroot().iter("skipped"))
sys.exit(0 if valid else 1)
PY
}

# Refuse ambiguous or stale artifact directories rather than selecting a glob match.
verify_dist() {
  python3 - "$1" <<'PY'
"""Require exactly one regular non-symlink wheel and source archive."""
import sys
from pathlib import Path
entries = list(Path(sys.argv[1]).iterdir())
valid = len(entries) == 2 and all(p.is_file() and not p.is_symlink() for p in entries)
valid &= sum(p.name.endswith(".whl") for p in entries) == 1
valid &= sum(p.name.endswith(".tar.gz") for p in entries) == 1
sys.exit(0 if valid else 1)
PY
}

# Validate owned canonical immediate-child paths and refuse every symlink component.
validate_owned_root() {
  python3 - "$RUNNER_TEMP" "$1" "${2:-}" <<'PY'
"""Authorize only private current-user scratch roots and optional state markers."""
import os
import stat
import sys
from pathlib import Path
base, root = map(Path, sys.argv[1:3])
valid = base.is_absolute() and root.is_absolute()
for path in (base, root):
    for component in (path, *path.parents):
        valid &= not component.is_symlink()
valid &= root.parent == base and root.name.startswith("lawci.")
valid &= root.is_dir() and root.resolve().parent == base.resolve()
if root.exists():
    info = root.stat()
    valid &= info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700
if sys.argv[3]:
    marker = Path(sys.argv[3])
    valid &= marker.parent == base and not marker.is_symlink() and marker.is_file()
    if marker.is_file():
        info = marker.stat()
        valid &= info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600
sys.exit(0 if valid else 1)
PY
}

# Remove only this lane's private scratch cluster; failed stop leaves evidence for retry.
cleanup_root() {
  local root="$1" pg_bin="$2" cluster="$1/data/private/postgres/cluster" boundary_path
  validate_owned_root "$root" || return 1
  for boundary_path in \
    "$root/data" "$root/data/private" "$root/data/private/postgres" \
    "$cluster" "$cluster/postmaster.pid"; do
    if [[ -L "$boundary_path" ]]; then
      printf '%s\n' 'law-ci: PostgreSQL cluster boundary is symlinked; scratch retained' >&2
      return 1
    fi
  done
  if [[ -e "$cluster" && ! -d "$cluster" ]]; then
    printf '%s\n' 'law-ci: PostgreSQL cluster path is not a directory; scratch retained' >&2
    return 1
  fi
  if [[ -d "$cluster" ]]; then
    if [[ ! -f "$cluster/postmaster.pid" ]]; then
      printf '%s\n' 'law-ci: PostgreSQL cluster PID metadata is missing; shutdown is inconclusive; scratch retained' >&2
      return 1
    fi
    "$pg_bin/pg_ctl" -D "$cluster" -m fast -w stop || return 1
    if [[ -e "$cluster/postmaster.pid" ]]; then
      printf '%s\n' 'law-ci: PostgreSQL stop returned success but PID metadata remains; scratch retained' >&2
      return 1
    fi
  fi
  rm -rf -- "$root"
}

# Preserve the failing child status and turn a failed database cleanup into failure.
on_exit() {
  local status=$?
  trap - EXIT INT TERM
  if ! cleanup_root "$scratch" "$pg_bin"; then
    printf '%s\n' 'law-ci: cleanup failed; owned scratch retained' >&2
    [[ "$status" != 0 ]] || status=1
  else
    if [[ "$state_owned" == 1 ]]; then rm -f -- "$state"; fi
  fi
  exit "$status"
}

# Execute committed source in a fresh short scratch root, never mutate the checkout.
run_ci() {
  [[ "${LAW_CI_SOURCE_SHA:-}" =~ ^[0-9a-f]{40}$ ]] &&
    [[ "$(git -C "${LAW_CI_SOURCE:-}" rev-parse HEAD)" == "$LAW_CI_SOURCE_SHA" ]] || {
      printf '%s\n' 'law-ci: source identity refused' >&2; return 1;
    }
  [[ "${LAW_CI_PYTHON_VERSION:-}" == 3.12 || "${LAW_CI_PYTHON_VERSION:-}" == 3.14 ]]
  [[ "$(uv --version)" == 'uv 0.12.5 '* ]]
  pg_bin="$(pg_config --bindir)"
  for tool in initdb pg_ctl createdb psql; do test -x "$pg_bin/$tool"; done
  test -d "${RUNNER_TEMP:?}"
  umask 077
  scratch="$(mktemp -d "$RUNNER_TEMP/lawci.XXXXXX")"
  state_owned=0
  state="$RUNNER_TEMP/law-ci-state-${LAW_CI_PYTHON_VERSION}"
  trap on_exit EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  test ! -e "$state" && test ! -L "$state"
  (set -o noclobber; printf '%s\n' "$scratch" > "$state")
  state_owned=1
  # Native Unix socket paths must remain shorter than the platform socket limit.
  test "${#scratch}" -lt 65
  export LAW_AGENT_ROOT="$scratch"
  export LAW_AGENT_POSTGRES_ROOT="$LAW_AGENT_ROOT"
  export LAW_AGENT_POSTGRES_USER
  LAW_AGENT_POSTGRES_USER="$(id -un)"
  export LAW_AGENT_POSTGRES_PORT=55439
  local private="$scratch/data/private/postgres"
  mkdir -p "$private/socket" "$scratch/source" "$scratch/out" "$scratch/outside"
  chmod 700 "$scratch" "$private" "$private/socket"
  # Consumer safety code requires this exact cluster/socket identity and test database.
  export LAW_AGENT_TEST_DATABASE_URL="dbname=law_agent_test user=$LAW_AGENT_POSTGRES_USER host=$private/socket port=$LAW_AGENT_POSTGRES_PORT"
  unset LAW_AGENT_DATABASE_URL PGHOSTADDR PGSERVICE PGSERVICEFILE PGSYSCONFDIR PGOPTIONS PYTHONPATH PYTHONHOME VIRTUAL_ENV
  export UV_CACHE_DIR="$scratch/uv-cache" UV_PROJECT_ENVIRONMENT="$scratch/venv"
  export UV_PYTHON="$LAW_CI_PYTHON_VERSION" UV_NO_CACHE=1
  printf '%s\n' 'law-ci: fresh native test cluster'
  "$pg_bin/initdb" -D "$private/cluster" -A trust -U "$LAW_AGENT_POSTGRES_USER" --encoding=UTF8 --no-locale > "$scratch/initdb.log"
  "$pg_bin/pg_ctl" -D "$private/cluster" -l "$scratch/server.log" \
    -o "-k $private/socket -p $LAW_AGENT_POSTGRES_PORT -c listen_addresses='' -c shared_buffers=32MB -c max_connections=15 -c statement_timeout=10s -c lock_timeout=2s" -w start
  "$pg_bin/createdb" -h "$private/socket" -p "$LAW_AGENT_POSTGRES_PORT" law_agent_test
  git -C "$LAW_CI_SOURCE" archive "$LAW_CI_SOURCE_SHA" | tar -x -C "$scratch/source"
  cd "$scratch/source"
  printf '%s\n' 'law-ci: locked source quality gates'
  uv sync --locked
  uv run --locked ruff check .
  uv run --locked ruff format --check .
  uv run --locked mypy
  # Fixtures need the complete archived migration inventory before suite collection.
  # Retain source evidence outside the checkout for the independent installed smoke.
  # Use the consumer's real test_only approval, not the broader development CLI path.
  uv run --locked python - "$scratch/source-migrations.json" <<'PY'
"""Commit the verified migrations to the fresh, approved test-only database."""
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from law_ai_agent.postgres import PostgresStore, connect
if sys.version_info[:2] != tuple(map(int, os.environ["LAW_CI_PYTHON_VERSION"].split("."))):
    raise SystemExit("law-ci: Python version mismatch")
# This path belongs to git archive's exact source, not an installed import fallback.
resources = Path("src/law_ai_agent/migrations")
inventory = []
versions = set()
for resource in sorted(resources.iterdir(), key=lambda path: path.name):
    match = re.fullmatch(r"([0-9]{3})_[a-z][a-z0-9]*(?:_[a-z0-9]+)*\.sql", resource.name)
    if not match or not resource.is_file() or resource.is_symlink():
        raise SystemExit("law-ci: source migration inventory invalid")
    version = int(match[1])
    script = resource.read_text()
    if version == 0 or version in versions or not script.strip():
        raise SystemExit("law-ci: source migration inventory invalid")
    versions.add(version)
    # Preserve PostgresStore.migrate's read_text()/script.encode() checksum semantics.
    inventory.append({"name": resource.name, "version": version,
                      "checksum": sha256(script.encode()).hexdigest()})
if not inventory:
    raise SystemExit("law-ci: source migration inventory invalid")
with connect(os.environ["LAW_AGENT_TEST_DATABASE_URL"], test_only=True) as connection:
    PostgresStore(connection).migrate()
    connection.commit()
    actual = [{"version": row["version"], "checksum": row["checksum"]}
              for row in connection.execute(
                  "SELECT version, checksum FROM law_agent.migration ORDER BY version")]
    expected = [{"version": row["version"], "checksum": row["checksum"]} for row in inventory]
    if actual != expected:
        raise SystemExit("law-ci: database migration inventory mismatch")
Path(sys.argv[1]).write_text(json.dumps(inventory))
PY
  uv run --locked pytest --cov --cov-fail-under=90 --cov-report=term-missing --junitxml="$scratch/junit.xml"
  bash "$SELF" verify-junit "$scratch/junit.xml"
  printf '%s\n' 'law-ci: fresh build and installed artifact smoke'
  uv build --out-dir "$scratch/out" --no-create-gitignore
  bash "$SELF" verify-dist "$scratch/out"
  # Prime dependency wheels into a new lane-local cache, then prove real offline install.
  uv venv --python "$LAW_CI_PYTHON_VERSION" "$scratch/prime"
  UV_NO_CACHE=0 uv pip install --python "$scratch/prime/bin/python" "$scratch/out/"*.whl
  uv venv --python "$LAW_CI_PYTHON_VERSION" "$scratch/installed"
  UV_NO_CACHE=0 uv pip install --offline --python "$scratch/installed/bin/python" "$scratch/out/"*.whl
  cd "$scratch/outside"
  "$scratch/installed/bin/python" -I - "$scratch/source-migrations.json" <<'PY'
"""Verify packaged migration resources outside the source checkout."""
from hashlib import sha256
from importlib.resources import files
import json
from pathlib import Path
import sys
import law_ai_agent
if not Path(law_ai_agent.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
    raise SystemExit("law-ci: installed package prefix mismatch")
expected = json.loads(Path(sys.argv[1]).read_text())
resources = sorted(files("law_ai_agent").joinpath("migrations").iterdir(), key=lambda path: path.name)
if not expected or [resource.name for resource in resources] != [row["name"] for row in expected]:
    raise SystemExit("law-ci: installed migration inventory mismatch")
for resource, row in zip(resources, expected):
    if not resource.is_file():
        raise SystemExit("law-ci: installed migration inventory mismatch")
    script = resource.read_text()
    if not script.strip() or sha256(script.encode()).hexdigest() != row["checksum"]:
        raise SystemExit("law-ci: installed migration inventory mismatch")
PY
  "$scratch/installed/bin/python" -I -m law_ai_agent --help > "$scratch/installed-help.log"
  printf '%s\n' 'law-ci: quality, zero-skip database and installed artifact gates passed'
}

# Recover a lane-local marker on GitHub cancellation; never source marker content.
cleanup_state() {
  local version state root pg_bin
  for version in 3.12 3.14; do
    state="${RUNNER_TEMP:?}/law-ci-state-$version"
    test -e "$state" || continue
    test ! -L "$state" && test -f "$state"
    IFS= read -r root < "$state"
    validate_owned_root "$root" "$state"
    pg_bin="$(pg_config --bindir)"
    cleanup_root "$root" "$pg_bin"
    rm -f -- "$state"
  done
}

case "${1:-}" in
  verify-junit) verify_junit "$2" ;;
  verify-dist) verify_dist "$2" ;;
  run) run_ci ;;
  cleanup) cleanup_state ;;
  *) printf '%s\n' 'law-ci: unknown operation' >&2; exit 1 ;;
esac
