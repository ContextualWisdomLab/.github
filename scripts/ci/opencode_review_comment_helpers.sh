#!/usr/bin/env bash

# Shared rendering helpers for the trusted central OpenCode review publisher.
# This file is sourced by workflow run blocks after the trusted .github
# repository has been checked out.

emit_change_flow_mermaid_graph() {
  local merge_state="${1:-UNKNOWN}"
  local changed_files_file surfaces_file idx next_node

  changed_files_file="$(mktemp)"
  surfaces_file="$(mktemp)"
  if ! timeout "${REVIEW_PUBLISH_GH_API_TIMEOUT_SECONDS:-120}s" \
    gh pr diff "$PR_NUMBER" --repo "$GH_REPOSITORY" --name-only >"$changed_files_file" 2>/dev/null ||
    [ ! -s "$changed_files_file" ]; then
    printf '```mermaid\n'
    printf 'flowchart LR\n'
    printf '  Evidence["OpenCode evidence"] --> Review["Current PR review path"]\n'
    printf '  Review --> Verify["Required checks"]\n'
    printf '```\n'
    rm -f "$changed_files_file" "$surfaces_file"
    return 0
  fi

  awk '
    function basename(path) {
      sub(/^.*\//, "", path)
      return path
    }
    function clean(value) {
      gsub(/"/, "", value)
      gsub(/[\r\n\t]/, " ", value)
      return value
    }
    function add(key, surface, impact, verify, path) {
      if (!(key in count)) {
        keys[++n] = key
        label[key] = surface ": " basename(path)
        impacts[key] = impact
        verifies[key] = verify
      }
      count[key]++
    }
    /^\.github\/workflows\// {
      add("workflow", "Workflow", "GitHub Actions review job", "actionlint plus required checks", $0)
      next
    }
    /^scripts\/ci\// {
      add("ci", "CI script", "review and security gate shell path", "bash -n plus Strix self-test", $0)
      next
    }
    /^backend\// {
      add("backend", "Backend", "API and service runtime", "backend tests", $0)
      next
    }
    /^frontend\// {
      add("frontend", "Frontend", "browser runtime and bundle", "frontend tests", $0)
      next
    }
    /^tests?\// || /(^|\/)test_/ {
      add("tests", "Test", "regression suite", "targeted test run", $0)
      next
    }
    /^docs\// {
      add("docs", "Docs", "operator or user guidance", "docs review", $0)
      next
    }
    {
      add("other", "Changed file", "repository behavior", "required checks", $0)
    }
    END {
      for (i = 1; i <= n; i++) {
        key = keys[i]
        if (count[key] > 1) {
          sub(/: .*/, " (" count[key] " files)", label[key])
        }
        print clean(label[key]) "\t" clean(impacts[key]) "\t" clean(verifies[key])
      }
    }
  ' "$changed_files_file" >"$surfaces_file"

  printf '```mermaid\n'
  printf 'flowchart LR\n'
  printf '  PR["PR changed files"] --> Evidence["OpenCode bounded evidence"]\n'
  idx=1
  while IFS="$(printf '\t')" read -r surface impact verify; do
    [ -n "$surface" ] || continue
    printf '  Evidence --> S%s["%s"]\n' "$idx" "$surface"
    printf '  S%s --> I%s["%s"]\n' "$idx" "$idx" "$impact"
    if [ "$merge_state" = "DIRTY" ] || [ "$merge_state" = "CONFLICTING" ]; then
      printf '  I%s --> Conflict["Merge conflict blocks this path"]\n' "$idx"
      next_node="Conflict"
    else
      printf '  I%s --> R%s["Review risk: %s"]\n' "$idx" "$idx" "$surface"
      next_node="R${idx}"
    fi
    printf '  %s --> V%s["%s"]\n' "$next_node" "$idx" "$verify"
    idx=$((idx + 1))
  done <"$surfaces_file"
  printf '```\n'
  rm -f "$changed_files_file" "$surfaces_file"
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
