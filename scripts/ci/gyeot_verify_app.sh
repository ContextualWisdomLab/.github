#!/usr/bin/env bash
# No host mutation: provision PostgreSQL and actionlint in the isolated runner image.
set -euo pipefail
helper_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${1:?Pass the admitted product checkout root}" && pwd)"
cd "$repository_root"

# Only the owned coverage directory is invalidated, including a stale symlink itself.
rm -rf -- "$repository_root/coverage"
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  printf '%s\n' 'coverage_ready=false' >> "$GITHUB_OUTPUT"
fi

if [[ "$(node -p 'process.versions.node.split(".")[0]')" != "24" ]]; then
  printf '%s\n' 'CI requires Node.js 24.' >&2
  exit 1
fi
npm ci --include=dev --no-audit --no-fund
npm --prefix .github ci --include=dev --ignore-scripts --no-audit --no-fund
npm --prefix .github test
actionlint
npm run typecheck
# Re-invalidate immediately before Jest so only that invocation can produce evidence.
rm -rf -- "$repository_root/coverage"
jest_status=0
npm test -- --ci --runInBand --coverage || jest_status=$?
if [[ -n "${GITHUB_OUTPUT:-}" && -f coverage/lcov.info && -s coverage/lcov.info && ! -L coverage && ! -L coverage/lcov.info ]]; then
  printf '%s\n' 'coverage_ready=true' >> "$GITHUB_OUTPUT"
fi
if [[ "$jest_status" -ne 0 ]]; then
  exit "$jest_status"
fi
bash "$helper_directory/gyeot_verify_export.sh" "$repository_root"
