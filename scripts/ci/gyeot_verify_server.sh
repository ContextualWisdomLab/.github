#!/usr/bin/env bash
# Discover existing PostgreSQL tools; never apt/sudo on a persistent runner.
set -euo pipefail
export LC_ALL=C
repository_root="$(cd "${1:?Pass the admitted product checkout root}" && pwd)"
cd "$repository_root"

if [[ "$(node -p 'process.versions.node.split(".")[0]')" != "24" ]]; then
  printf '%s\n' 'CI requires Node.js 24.' >&2
  exit 1
fi
if ! command -v initdb >/dev/null 2>&1; then
  postgres_bin_dir=""
  for candidate_dir in /usr/lib/postgresql/*/bin; do
    if [[ -x "$candidate_dir/initdb" ]]; then
      postgres_bin_dir="$candidate_dir"
    fi
  done
  if [[ -z "$postgres_bin_dir" ]]; then
    printf '%s\n' 'Provision PostgreSQL server binaries in the isolated CI image.' >&2
    exit 1
  fi
  export PATH="$postgres_bin_dir:$PATH"
fi
for required_tool in initdb pg_ctl psql createdb; do
  command -v "$required_tool" >/dev/null
done
if [[ "$(id -u)" == "0" ]]; then
  printf '%s\n' 'PostgreSQL integration tests require a non-root runner user.' >&2
  exit 1
fi
npm --prefix server ci --include=dev --no-audit --no-fund
npm --prefix server run typecheck
npm --prefix server run test:unit
bash server/db/test_rls.sh
bash server/db/test_server.sh
# PR #58 owns this additional regression; pick it up after normal integration.
if [[ -f server/db/test_migrations.sh ]]; then
  bash server/db/test_migrations.sh
fi
