#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 6 ]; then
  echo "usage: $0 <repo> <run-id> <default-branch> <classified-default-sha> <classified-open-pr-heads-json> <superseded|aged-orphan>" >&2
  exit 2
fi

repo_full_name="$1"
run_id="$2"
default_branch="$3"
classified_default_sha="$4"
classified_open_pr_heads_json="$5"
cancellation_mode="$6"

case "$cancellation_mode" in
  superseded|aged-orphan) ;;
  *)
    echo "invalid cancellation mode: ${cancellation_mode}" >&2
    exit 2
    ;;
esac

warn_preserve() {
  echo "::warning::Preserving run ${run_id} in ${repo_full_name}: $1"
  exit 0
}

encode_ref_path() {
  jq -rn --arg value "$1" '$value | split("/") | map(@uri) | join("/")'
}

if ! run_json="$(gh api -H "Accept: application/vnd.github+json" "/repos/${repo_full_name}/actions/runs/${run_id}")"; then
  warn_preserve "live run metadata could not be re-fetched before cancellation."
fi

event="$(jq -r '.event // empty' <<<"$run_json")"
status="$(jq -r '.status // empty' <<<"$run_json")"
run_head="$(jq -r '.head_sha // empty' <<<"$run_json")"
run_branch="$(jq -r '.head_branch // empty' <<<"$run_json")"
run_head_repo="$(jq -r '.head_repository.full_name // empty' <<<"$run_json")"
if ! [[ "$run_head" =~ ^[0-9a-fA-F]{40}$ ]]; then
  warn_preserve "live run head is malformed."
fi

if [ "$cancellation_mode" = "aged-orphan" ]; then
  if [ "$status" != "queued" ]; then
    warn_preserve "aged-orphan candidate is no longer queued (status=${status:-<missing>})."
  fi
elif [ "$status" != "queued" ] && [ "$status" != "in_progress" ]; then
  warn_preserve "superseded candidate is no longer queued or in progress (status=${status:-<missing>})."
fi

case "$event" in
  pull_request|pull_request_target)
    pr_number="$(jq -r '.pull_requests[0].number // empty' <<<"$run_json")"
    if ! [[ "$pr_number" =~ ^[1-9][0-9]*$ ]]; then
      if [ "$cancellation_mode" = "aged-orphan" ]; then
        # Association metadata on an Actions run can lag the PR itself. Re-read
        # open PRs immediately before destructive cancellation, but use that
        # payload only to discover the authoritative head repository/ref. The
        # payload SHA itself can be stale, so resolve a matching branch through
        # the Git reference endpoint before deciding whether the run is current.
        if [ -z "$run_head_repo" ] || [ -z "$run_branch" ]; then
          warn_preserve "unassociated PR run has no authoritative head repository/ref."
        fi
        if ! fresh_open_pr_refs_json="$(
          gh api \
            -H "Accept: application/vnd.github+json" \
            "/repos/${repo_full_name}/pulls?state=open&per_page=100" \
            --paginate \
            | jq -sc '[.[] | .[] | {
                repo: (.head.repo.full_name // null),
                ref: (.head.ref // null)
              }]'
        )"; then
          warn_preserve "open PR heads could not be re-fetched for an unassociated PR run."
        fi
        if ! jq -e '
          all(.[];
            (.repo | type) == "string" and (.repo | length) > 0 and
            (.ref | type) == "string" and (.ref | length) > 0
          )
        ' <<<"$fresh_open_pr_refs_json" >/dev/null; then
          warn_preserve "fresh open PR head evidence is malformed."
        fi
        if jq -e \
          --arg repo "$run_head_repo" \
          --arg ref "$run_branch" \
          'any(.[]; .repo == $repo and .ref == $ref)' \
          <<<"$fresh_open_pr_refs_json" >/dev/null; then
          encoded_run_ref="$(encode_ref_path "$run_branch")"
          if ! final_ref_sha="$(
            gh api \
              -H "Accept: application/vnd.github+json" \
              "/repos/${run_head_repo}/git/ref/heads/${encoded_run_ref}" \
              --jq '.object.sha // empty'
          )"; then
            warn_preserve "live ref for newly associated PR head could not be re-fetched before cancellation."
          fi
          if ! [[ "$final_ref_sha" =~ ^[0-9a-fA-F]{40}$ ]]; then
            warn_preserve "live ref for newly associated PR head is malformed."
          fi
          if [ "$run_head" = "$final_ref_sha" ]; then
            warn_preserve "run became associated with an open PR at its authoritative current head after queue classification."
          fi
        fi
      else
        warn_preserve "no authoritative PR identity is attached to the live run."
      fi
    else
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
        encoded_head_ref="$(encode_ref_path "$live_head_ref")"
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
      # A closed PR cannot supply current merge evidence. If the run is still
      # active and was selected from the trusted snapshot, closure remains an
      # authoritative reason to retire it.
    fi
    ;;
  push|schedule)
    if [ "$run_branch" = "$default_branch" ] || [ "$cancellation_mode" = "superseded" ]; then
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
    fi
    ;;
  *)
    if [ "$cancellation_mode" = "superseded" ]; then
      warn_preserve "event ${event:-<missing>} is outside the authoritative superseded-run contract."
    fi
    # Aged-orphan mode intentionally retains the legacy cleanup contract for
    # workflow_dispatch, workflow_run, repository_dispatch, and other queued
    # events that the trusted initial snapshot proved were not current PR heads.
    ;;
esac

if ! gh api -X POST "/repos/${repo_full_name}/actions/runs/${run_id}/cancel" >/dev/null; then
  echo "Could not cancel ${cancellation_mode} run ${run_id} in ${repo_full_name}; it may have started or finished already."
fi
