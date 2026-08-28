#!/usr/bin/env bash

# Shared rendering helpers for the trusted central OpenCode review publisher.
# This file is sourced by workflow run blocks after the trusted .github
# repository has been checked out.
#
# Honesty-surface mermaid contract. Runtime graphs come from
# opencode_review_surfaces.py emit_mermaid (no invented edges, no generic
# "Changed file (N files)"). Quoted labels are required; unquoted breaks mermaid.
# The python emitter keeps these phrases:
#   OpenCode bounded evidence
#   GitHub Actions review job
#   Merge conflict blocks this path

opencode_mermaid_quoted_surface_node() {
  # Quoted mermaid surface node, e.g. S1["Workflow: ci.yml"]
  printf 'S%s["%s"]' "$1" "$2"
}

opencode_mermaid_quoted_risk_node() {
  # Quoted mermaid risk node, e.g. R1["Review risk: Workflow: ci.yml"]
  printf 'R%s["Review risk: %s"]' "$1" "$2"
}

opencode_review_surfaces_py() {
  local helper_dir
  helper_dir="$(CDPATH='' cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
  printf '%s' "${helper_dir}/opencode_review_surfaces.py"
}

emit_change_flow_mermaid_graph() {
  local merge_state="${1:-UNKNOWN}"
  local changed_files_file

  changed_files_file="$(mktemp)"
  if ! timeout "${REVIEW_PUBLISH_GH_API_TIMEOUT_SECONDS:-120}s" \
    gh pr diff "$PR_NUMBER" --repo "$GH_REPOSITORY" --name-only >"$changed_files_file" 2>/dev/null ||
    [ ! -s "$changed_files_file" ]; then
    if [ -n "${OPENCODE_CHANGED_FILES_FILE:-}" ] && [ -s "${OPENCODE_CHANGED_FILES_FILE}" ]; then
      cp "${OPENCODE_CHANGED_FILES_FILE}" "$changed_files_file"
    fi
  fi
  if [ -n "${OPENCODE_SOURCE_WORKDIR:-}" ]; then
    python3 "$(opencode_review_surfaces_py)" emit-mermaid \
      --changed-files-file "$changed_files_file" \
      --source-root "$OPENCODE_SOURCE_WORKDIR" \
      --merge-state "$merge_state"
  else
    python3 "$(opencode_review_surfaces_py)" emit-mermaid \
      --changed-files-file "$changed_files_file" \
      --merge-state "$merge_state"
  fi
  rm -f "$changed_files_file"
}

append_mermaid_review_graph() {
  local pr_json merge_state
  pr_json="$(timeout "${REVIEW_PUBLISH_GH_API_TIMEOUT_SECONDS:-120}s" \
    gh pr view "$PR_NUMBER" --repo "$GH_REPOSITORY" --json mergeStateStatus 2>/dev/null || true)"
  merge_state="$(printf '%s' "$pr_json" | jq -r '.mergeStateStatus // "UNKNOWN"' 2>/dev/null || printf 'UNKNOWN')"
  printf '\n## Changed-File Evidence Map\n\n'
  emit_change_flow_mermaid_graph "$merge_state"
}

ensure_review_body_has_change_graph() {
  local body="$1"
  printf '%s\n' "$body"
  if grep -Fq "## Changed-File Evidence Map" <<<"$body"; then
    return 0
  fi
  append_mermaid_review_graph
}

append_merge_conflict_guidance() {
  local pr_json merge_state base_ref head_ref base_fetch_ref base_origin_ref head_push_ref
  pr_json="$(timeout "${REVIEW_PUBLISH_GH_API_TIMEOUT_SECONDS:-120}s" \
    gh pr view "$PR_NUMBER" --repo "$GH_REPOSITORY" --json baseRefName,headRefName,mergeStateStatus 2>/dev/null || true)"
  if [ -z "$pr_json" ]; then
    return 0
  fi
  merge_state="$(printf '%s' "$pr_json" | jq -r '.mergeStateStatus // ""')"
  if [ "$merge_state" != "DIRTY" ] && [ "$merge_state" != "CONFLICTING" ]; then
    return 0
  fi
  base_ref="$(printf '%s' "$pr_json" | jq -r '.baseRefName // "base"')"
  head_ref="$(printf '%s' "$pr_json" | jq -r '.headRefName // "head"')"
  printf -v base_fetch_ref '%q' "$base_ref"
  printf -v base_origin_ref '%q' "origin/${base_ref}"
  printf -v head_push_ref '%q' "HEAD:${head_ref}"
  printf '\n## Merge Conflict Guidance\n\n'
  printf '%s\n' "- Current merge state: \`${merge_state}\`"
  printf '%s\n' "- Base branch: \`${base_ref}\`"
  printf '%s\n' "- Head branch: \`${head_ref}\`"
  printf '%s\n' "- Fix direction: merge or rebase \`origin/${base_ref}\` into \`${head_ref}\`, resolve conflict markers in the changed files, rerun the focused checks, then push the same branch."
  printf '%s\n' "- Repair commands:"
  printf '%s\n' '```bash'
  printf 'gh pr checkout %s --repo %s\n' "$PR_NUMBER" "$GH_REPOSITORY"
  printf 'git fetch origin %s\n' "$base_fetch_ref"
  printf 'git merge --no-ff %s  # or: git rebase %s\n' "$base_origin_ref" "$base_origin_ref"
  printf 'git status --short\n'
  printf '# resolve files, then git add <resolved-files>\n'
  printf '# merge path: git commit\n'
  printf '# rebase path: git rebase --continue\n'
  printf 'git push origin %s\n' "$head_push_ref"
  printf '# rebase path only: git push --force-with-lease origin %s\n' "$head_push_ref"
  printf '%s\n' '```'
}
