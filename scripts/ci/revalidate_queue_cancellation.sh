#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 5 ]; then
  echo "usage: $0 <repo> <run-id> <default-branch> <classified-default-sha> <classified-open-pr-heads-json>" >&2
  exit 2
fi

repo_full_name="$1"
run_id="$2"
default_branch="$3"
classified_default_sha="$4"
classified_open_pr_heads_json="$5"

warn_preserve() {
  echo "::warning::Preserving run ${run_id} in ${repo_full_name}: $1"
  exit 0
}

if ! run_json="$(gh api -H "Accept: application/vnd.github+json" "/repos/${repo_full_name}/actions/runs/${run_id}")"; then
  warn_preserve "live run metadata could not be re-fetched before cancellation."
fi

event="$(jq -r '.event // empty' <<<"$run_json")"
run_head="$(jq -r '.head_sha // empty' <<<"$run_json")"
if ! [[ "$run_head" =~ ^[0-9a-fA-F]{40}$ ]]; then
  warn_preserve "live run head is malformed."
fi

case "$event" in
  pull_request|pull_request_target)
    pr_number="$(jq -r '.pull_requests[0].number // empty' <<<"$run_json")"
    if ! [[ "$pr_number" =~ ^[1-9][0-9]*$ ]]; then
      warn_preserve "no authoritative PR identity is attached to the live run."
    fi
    if ! pr_json="$(gh api -H "Accept: application/vnd.github+json" "/repos/${repo_full_name}/pulls/${pr_number}")"; then
      warn_preserve "live PR ${pr_number} could not be re-fetched before cancellation."
    fi
    live_state="$(jq -r '.state // empty' <<<"$pr_json")"
    if [ "$live_state" = "open" ]; then
      live_head_repo="$(jq -r '.head.repo.full_name // empty' <<<"$pr_json")"
      live_head_ref="$(jq -r '.head.ref // empty' <<<"$pr_json")"
      live_head_sha="$(jq -r '.head.sha // empty' <<<"$pr_json")"
      if [ -z "$live_head_repo" ] || [ -z "$live_head_ref" ] || ! [[ "$live_head_sha" =~ ^[0-9a-fA-F]{40}$ ]]; then
        warn_preserve "live PR ${pr_number} head metadata is malformed."
      fi
      encoded_head_ref="$(jq -rn --arg value "$live_head_ref" '$value | split("/") | map(@uri) | join("/")')"
      if ! final_ref_sha="$(gh api -H "Accept: application/vnd.github+json" "/repos/${live_head_repo}/git/ref/heads/${encoded_head_ref}" --jq '.object.sha // empty')"; then
        warn_preserve "live ref for PR ${pr_number} could not be re-fetched before cancellation."
      fi
      if ! [[ "$final_ref_sha" =~ ^[0-9a-fA-F]{40}$ ]]; then
        warn_preserve "live ref for PR ${pr_number} is malformed."
      fi
      classified_sha="$(jq -r --arg key "${live_head_repo}:${live_head_ref}" '.[$key] // empty' <<<"$classified_open_pr_heads_json")"
      if ! [[ "$classified_sha" =~ ^[0-9a-fA-F]{40}$ ]]; then
        warn_preserve "the classification snapshot has no valid head for PR ${pr_number}."
      fi
      if [ "$live_head_sha" != "$classified_sha" ] || [ "$final_ref_sha" != "$classified_sha" ]; then
        warn_preserve "PR ${pr_number} moved after queue classification."
      fi
      if [ "$run_head" = "$final_ref_sha" ]; then
        echo "Preserving run ${run_id} in ${repo_full_name}: authoritative current-head evidence for PR ${pr_number}."
        exit 0
      fi
    elif [ "$live_state" != "closed" ]; then
      warn_preserve "live PR ${pr_number} state is malformed."
    fi
    ;;
  push|schedule)
    if ! live_default_sha="$(gh api -H "Accept: application/vnd.github+json" "/repos/${repo_full_name}/commits/${default_branch}" --jq '.sha // empty')"; then
      warn_preserve "live default-branch HEAD could not be re-fetched before cancellation."
    fi
    if ! [[ "$live_default_sha" =~ ^[0-9a-fA-F]{40}$ ]]; then
      warn_preserve "live default-branch HEAD is malformed."
    fi
    if [ "$live_default_sha" != "$classified_default_sha" ]; then
      warn_preserve "default branch moved after queue classification."
    fi
    if [ "$run_head" = "$live_default_sha" ]; then
      echo "Preserving run ${run_id} in ${repo_full_name}: authoritative current default-branch evidence."
      exit 0
    fi
    ;;
  *)
    warn_preserve "event ${event:-<missing>} is outside the authoritative superseded-run contract."
    ;;
esac

if ! gh api -X POST "/repos/${repo_full_name}/actions/runs/${run_id}/cancel" >/dev/null; then
  echo "Could not cancel superseded run ${run_id} in ${repo_full_name}; it may have finished already."
fi
