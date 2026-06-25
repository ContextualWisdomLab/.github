#!/usr/bin/env bash
set -euo pipefail

repo_root="$(
  CDPATH=''
  cd -P -- "$(dirname -- "$0")/../.."
  pwd -P
)"
workflow_file="$repo_root/.github/workflows/opencode-review.yml"

check_contains() {
  local needle="$1"
  if ! grep -Fq -- "$needle" "$workflow_file"; then
    printf 'missing OpenCode fact-gate contract: %s\n' "$needle" >&2
    exit 1
  fi
}

check_contains '## Changed docs repository tree evidence'
check_contains 'git -C "$OPENCODE_SOURCE_WORKDIR" ls-tree -r --name-only "$PR_HEAD_SHA" -- "$docs_dir"'
check_contains 'Do not claim repository docs, images, or reference assets are unavailable, missing, or absent unless the changed docs repository tree evidence proves it.'
check_contains 'collect_unresolved_human_review_threads()'
check_contains 'reviewThreads(first: 100)'
check_contains 'Latest unresolved human review thread evidence'
check_contains 'OpenCode reviewed the current-head evidence but found unresolved human review threads before approval.'
check_contains 'bounded-review-evidence-excerpt.md'
check_contains 'Current-head bounded evidence excerpt, inlined to prevent false no-change or no-coverage approvals when tool/file reads are skipped:'
check_contains 'emit_review_body_to_action_log()'
check_contains '::stop-commands::%s'
check_contains 'OpenCode is publishing this review content to PR #%s.'
check_contains '## Inline review comments'

printf 'OpenCode fact-gate contract OK\n'
