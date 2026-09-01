#!/usr/bin/env bash
set -euo pipefail

: "${TARGET_REPOSITORY:?TARGET_REPOSITORY is required}"
: "${PR_NUMBER:?PR_NUMBER is required}"
: "${EXPECTED_HEAD_SHA:?EXPECTED_HEAD_SHA is required}"
: "${PR_BASE_SHA:?PR_BASE_SHA is required}"
: "${NOEMA_CODEGRAPH_CONTEXT_PATH:?NOEMA_CODEGRAPH_CONTEXT_PATH is required}"
: "${GH_TOKEN:?GH_TOKEN is required for source materialization}"

if ! [[ "$TARGET_REPOSITORY" =~ ^ContextualWisdomLab/[A-Za-z0-9_.-]+$ ]] ||
  ! [[ "$PR_NUMBER" =~ ^[1-9][0-9]*$ ]] ||
  ! [[ "$EXPECTED_HEAD_SHA" =~ ^[0-9a-fA-F]{40}$ ]] ||
  ! [[ "$PR_BASE_SHA" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "::error::Noema CodeGraph source metadata is malformed."
  exit 1
fi

CODEGRAPH_TRUSTED_ROOT="${RUNNER_TEMP:?}/trusted-noema-codegraph"
source_root="${RUNNER_TEMP}/noema-codegraph-pr-source"
askpass="${RUNNER_TEMP}/noema-codegraph-askpass.sh"
rm -rf "$CODEGRAPH_TRUSTED_ROOT" "$source_root"
rm -f "$NOEMA_CODEGRAPH_CONTEXT_PATH" "$askpass"
mkdir -p "$CODEGRAPH_TRUSTED_ROOT" "$source_root"

cat >"$askpass" <<'ASKPASS'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  *Username*) printf '%s\n' x-access-token ;;
  *) printf '%s\n' "${GH_TOKEN:?}" ;;
esac
ASKPASS
chmod 0700 "$askpass"

git -C "$source_root" init -q
git -C "$source_root" remote add origin "https://github.com/${TARGET_REPOSITORY}.git"
GIT_ASKPASS="$askpass" GIT_ASKPASS_REQUIRE=force GIT_TERMINAL_PROMPT=0 \
  git -C "$source_root" fetch --no-tags --depth=1 origin "refs/pull/${PR_NUMBER}/head"
observed_head="$(git -C "$source_root" rev-parse FETCH_HEAD)"
if [ "${observed_head,,}" != "${EXPECTED_HEAD_SHA,,}" ]; then
  echo "::error::Noema CodeGraph PR ref is stale; expected ${EXPECTED_HEAD_SHA}, observed ${observed_head}."
  exit 1
fi
git -C "$source_root" update-ref refs/noema/head "$observed_head"
GIT_ASKPASS="$askpass" GIT_ASKPASS_REQUIRE=force GIT_TERMINAL_PROMPT=0 \
  git -C "$source_root" fetch --no-tags --depth=1 origin "$PR_BASE_SHA"
observed_base="$(git -C "$source_root" rev-parse FETCH_HEAD)"
if [ "${observed_base,,}" != "${PR_BASE_SHA,,}" ]; then
  echo "::error::Noema CodeGraph base ref did not materialize at the expected SHA."
  exit 1
fi
git -C "$source_root" update-ref refs/noema/base "$observed_base"

merge_base=""
if ! merge_base="$(git -C "$source_root" merge-base refs/noema/base refs/noema/head 2>/dev/null)"; then
  merge_base=""
fi
for deepen_by in 64 256 1024 4096; do
  [ -n "$merge_base" ] && break
  GIT_ASKPASS="$askpass" GIT_ASKPASS_REQUIRE=force GIT_TERMINAL_PROMPT=0 \
    git -C "$source_root" fetch --no-tags --deepen="$deepen_by" origin \
      "refs/pull/${PR_NUMBER}/head" "$PR_BASE_SHA"
  if ! merge_base="$(git -C "$source_root" merge-base refs/noema/base refs/noema/head 2>/dev/null)"; then
    merge_base=""
  fi
done
if ! [[ "$merge_base" =~ ^[0-9a-fA-F]{40}$ ]] ||
  ! git -C "$source_root" merge-base --is-ancestor "$merge_base" refs/noema/head ||
  ! git -C "$source_root" merge-base --is-ancestor "$merge_base" refs/noema/base; then
  echo "::error::Noema CodeGraph could not establish a bounded exact merge base for the reviewed pull request."
  exit 1
fi
materialized_head="$(git -C "$source_root" rev-parse refs/noema/head)"
materialized_base="$(git -C "$source_root" rev-parse refs/noema/base)"
if [ "${materialized_head,,}" != "${EXPECTED_HEAD_SHA,,}" ] ||
  [ "${materialized_base,,}" != "${PR_BASE_SHA,,}" ]; then
  echo "::error::Noema CodeGraph exact source refs moved while materializing merge-base history."
  exit 1
fi

git -C "$source_root" checkout -q --detach refs/noema/head
rm -f "$askpass"
# The checkout is attacker-controlled review input. Strip every credential this
# review step can provide before invoking package tooling or CodeGraph. The
# loader calls this helper before it reads the sidecar bearer, and these unsets
# are defense-in-depth for direct or legacy callers that already exported it.
unset \
  GH_TOKEN GITHUB_TOKEN \
  ACTIONS_ID_TOKEN_REQUEST_TOKEN ACTIONS_ID_TOKEN_REQUEST_URL ACTIONS_RUNTIME_TOKEN \
  CONTEXTUAL_ORCHESTRATOR_TOKEN CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE

for manifest in \
  "$GITHUB_WORKSPACE/scripts/ci/codegraph-package/package.json" \
  "$GITHUB_WORKSPACE/scripts/ci/codegraph-package/package-lock.json"; do
  if [ ! -f "$manifest" ] || [ -L "$manifest" ]; then
    echo "::error::Trusted Noema CodeGraph package input is missing or symlinked: $manifest"
    exit 1
  fi
done
cp "$GITHUB_WORKSPACE/scripts/ci/codegraph-package/package.json" \
  "$GITHUB_WORKSPACE/scripts/ci/codegraph-package/package-lock.json" \
  "$CODEGRAPH_TRUSTED_ROOT"/
(
  cd "$CODEGRAPH_TRUSTED_ROOT"
  NPM_CONFIG_IGNORE_SCRIPTS=true npm ci --ignore-scripts --omit=dev --no-audit --no-fund
  NPM_CONFIG_IGNORE_SCRIPTS=true npm audit --package-lock-only --omit=dev --audit-level=moderate
)

PATCHED_PICOMATCH_DIR="$CODEGRAPH_TRUSTED_ROOT/node_modules/picomatch"
patched_picomatch_version="$(
  node -e 'const fs=require("fs"); console.log(JSON.parse(fs.readFileSync(process.argv[1], "utf8")).version)' \
    "$PATCHED_PICOMATCH_DIR/package.json"
)"
if [ "$patched_picomatch_version" != "4.0.4" ]; then
  echo "::error::Trusted Noema CodeGraph hardening requires picomatch 4.0.4; found ${patched_picomatch_version:-missing}."
  exit 1
fi

mapfile -t codegraph_platforms < <(
  find "$CODEGRAPH_TRUSTED_ROOT/node_modules/@colbymchenry" \
    -mindepth 1 -maxdepth 1 -type d -name 'codegraph-*' -print
)
hardened_bundle_count=0
for codegraph_platform in "${codegraph_platforms[@]}"; do
  bundled_picomatch="$codegraph_platform/lib/node_modules/picomatch"
  bundled_lock="$codegraph_platform/lib/node_modules/.package-lock.json"
  [ -d "$bundled_picomatch" ] || continue
  resolved_bundle="$(realpath "$bundled_picomatch")"
  case "$resolved_bundle" in
    "$CODEGRAPH_TRUSTED_ROOT"/node_modules/@colbymchenry/codegraph-*/lib/node_modules/picomatch) ;;
    *)
      echo "::error::Refusing to harden CodeGraph outside the trusted package root: $resolved_bundle"
      exit 1
      ;;
  esac
  if [ ! -f "$bundled_lock" ]; then
    echo "::error::CodeGraph platform bundle is missing its nested dependency lock: $bundled_lock"
    exit 1
  fi
  rm -rf "$bundled_picomatch"
  mkdir -p "$bundled_picomatch"
  cp -R "$PATCHED_PICOMATCH_DIR"/. "$bundled_picomatch"/
  patched_lock="$(mktemp)"
  jq --slurpfile trusted_lock "$CODEGRAPH_TRUSTED_ROOT/package-lock.json" \
    '.packages["node_modules/picomatch"] = $trusted_lock[0].packages["node_modules/picomatch"]' \
    "$bundled_lock" >"$patched_lock"
  mv "$patched_lock" "$bundled_lock"
  installed_version="$(
    node -e 'const fs=require("fs"); console.log(JSON.parse(fs.readFileSync(process.argv[1], "utf8")).version)' \
      "$bundled_picomatch/package.json"
  )"
  locked_version="$(jq -r '.packages["node_modules/picomatch"].version // empty' "$bundled_lock")"
  if [ "$installed_version" != "4.0.4" ] || [ "$locked_version" != "4.0.4" ]; then
    echo "::error::Noema CodeGraph nested picomatch hardening failed."
    exit 1
  fi
  hardened_bundle_count=$((hardened_bundle_count + 1))
done
if [ "$hardened_bundle_count" -lt 1 ]; then
  echo "::error::No installed CodeGraph platform bundle exposed a nested picomatch package to harden."
  exit 1
fi

CODEGRAPH_BIN="$CODEGRAPH_TRUSTED_ROOT/node_modules/.bin/codegraph"
test -x "$CODEGRAPH_BIN"
export CODEGRAPH_NO_DOWNLOAD=1
codegraph_status="$(mktemp)"
codegraph_raw="$(mktemp)"
changed_scope="$(git -C "$source_root" diff --name-only "$merge_base" refs/noema/head | sed -n '1,80p' | tr '\n' ' ')"
cd "$source_root"
"$CODEGRAPH_BIN" init -i
if ! "$CODEGRAPH_BIN" status >"$codegraph_status" 2>&1; then
  cat "$codegraph_status" >&2
  echo "::error::Noema CodeGraph status failed."
  exit 1
fi
if ! timeout 120s "$CODEGRAPH_BIN" explore \
  "Review blast radius, callers/callees, dependency paths, authority boundaries, state transitions, and focused tests for these exact-head changed files: ${changed_scope}" \
  >"$codegraph_raw" 2>&1; then
  cat "$codegraph_raw" >&2
  echo "::error::Noema CodeGraph changed-scope exploration failed."
  exit 1
fi
{
  printf '# Trusted CodeGraph current-head evidence\n\n'
  printf -- '- Head SHA: `%s`\n' "$EXPECTED_HEAD_SHA"
  printf -- '- Base SHA: `%s`\n' "$PR_BASE_SHA"
  printf -- '- Merge-base SHA: `%s`\n\n' "$merge_base"
  printf '## CodeGraph status\n\n'
  head -c 3000 "$codegraph_status"
  printf '\n\n## Changed-scope exploration\n\n'
  head -c 15000 "$codegraph_raw"
} >"$NOEMA_CODEGRAPH_CONTEXT_PATH"
rm -f "$codegraph_status" "$codegraph_raw"
test -s "$NOEMA_CODEGRAPH_CONTEXT_PATH"
