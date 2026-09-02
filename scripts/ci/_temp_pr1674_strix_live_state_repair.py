"""One-shot exact-source repair for PR 1674; self-retired after validation."""

from pathlib import Path

workflow_path = Path(".github/workflows/strix.yml")
text = workflow_path.read_text(encoding="utf-8")

start_marker = "      - name: Validate repository dispatch against live pull request metadata\n"
next_marker = "      - name: Fetch pull request head for trusted scan\n"
visibility_marker = "      - name: Resolve target repository visibility\n"
start = text.index(start_marker)
end = text.index(next_marker, start)
validation_step = text[start:end]
text = text[:start] + text[end:]

repaired_validation = r'''      - name: Validate repository dispatch against live pull request metadata
        id: dispatch_validation
        if: github.event_name == 'repository_dispatch'
        env:
          GH_TOKEN: ${{ steps.target_app_token.outputs.token || secrets.OPENCODE_APPROVE_TOKEN || github.token }}
          REPOSITORY: ${{ github.event.client_payload.target_repository }}
          PR_NUMBER: ${{ github.event.client_payload.pr_number }}
          SUPPLIED_BASE_REF: ${{ github.event.client_payload.pr_base_ref }}
          SUPPLIED_BASE_SHA: ${{ github.event.client_payload.pr_base_sha }}
          SUPPLIED_HEAD_SHA: ${{ github.event.client_payload.pr_head_sha }}
        run: |
          set -euo pipefail
          if ! [[ "$REPOSITORY" =~ ^ContextualWisdomLab/[A-Za-z0-9_.-]+$ ]] ||
            ! [[ "$PR_NUMBER" =~ ^[1-9][0-9]*$ ]] ||
            ! [[ "$SUPPLIED_BASE_SHA" =~ ^[0-9a-fA-F]{40}$ ]] ||
            ! [[ "$SUPPLIED_HEAD_SHA" =~ ^[0-9a-fA-F]{40}$ ]] ||
            [ -z "$SUPPLIED_BASE_REF" ]; then
            echo "::error::repository_dispatch Strix metadata is incomplete or malformed."
            exit 1
          fi

          if ! pull_request_json="$(gh api "repos/${REPOSITORY}/pulls/${PR_NUMBER}")"; then
            echo "::error::Could not revalidate live repository_dispatch Strix pull request metadata."
            exit 1
          fi
          live_state="$(jq -r '.state // empty' <<<"$pull_request_json")"
          live_draft="$(jq -r 'if .draft == true then "true" elif .draft == false then "false" else empty end' <<<"$pull_request_json")"
          live_base_repository="$(jq -r '.base.repo.full_name // empty' <<<"$pull_request_json")"
          live_head_repository="$(jq -r '.head.repo.full_name // empty' <<<"$pull_request_json")"
          live_base_ref="$(jq -r '.base.ref // empty' <<<"$pull_request_json")"
          live_base_sha="$(jq -r '.base.sha // empty' <<<"$pull_request_json")"
          live_head_sha="$(jq -r '.head.sha // empty' <<<"$pull_request_json")"

          if [ -z "$live_state" ] || [ -z "$live_draft" ] ||
            [ "$live_base_repository" != "$REPOSITORY" ] ||
            [ "$live_head_sha" != "$SUPPLIED_HEAD_SHA" ]; then
            printf '::error::repository_dispatch Strix target identity/head is stale or unverifiable for %s#%s. supplied head=%s; live state=%s draft=%s base_repo=%s head_repo=%s head=%s.\n' \
              "$REPOSITORY" "$PR_NUMBER" "$SUPPLIED_HEAD_SHA" "${live_state:-missing}" "${live_draft:-missing}" \
              "${live_base_repository:-missing}" "${live_head_repository:-missing}" "${live_head_sha:-missing}"
            exit 1
          fi

          if [ "$live_state" = "closed" ]; then
            echo "should_scan=false" >>"$GITHUB_OUTPUT"
            printf '::notice::repository_dispatch Strix target closed on exact head %s; skipping resolved work.\n' "$live_head_sha"
            exit 0
          fi
          if [ "$live_state" != "open" ]; then
            echo "::error::repository_dispatch Strix target has unexpected live state '$live_state'."
            exit 1
          fi
          if [ "$live_draft" = "true" ]; then
            echo "should_scan=false" >>"$GITHUB_OUTPUT"
            printf '::notice::repository_dispatch Strix target is now draft on exact head %s; skipping until live ready state is restored.\n' "$live_head_sha"
            exit 0
          fi
          if [ "$live_draft" != "false" ] ||
            [ "$live_head_repository" != "$REPOSITORY" ] ||
            [ "$live_base_ref" != "$SUPPLIED_BASE_REF" ] ||
            [ "$live_base_sha" != "$SUPPLIED_BASE_SHA" ]; then
            printf '::error::repository_dispatch Strix metadata does not match the live ready PR %s#%s. supplied base=%s/%s head=%s; live state=%s draft=%s base_repo=%s base=%s/%s head_repo=%s head=%s.\n' \
              "$REPOSITORY" "$PR_NUMBER" "$SUPPLIED_BASE_REF" "$SUPPLIED_BASE_SHA" "$SUPPLIED_HEAD_SHA" \
              "$live_state" "$live_draft" "$live_base_repository" "${live_base_ref:-missing}" "${live_base_sha:-missing}" \
              "${live_head_repository:-missing}" "$live_head_sha"
            exit 1
          fi

          echo "should_scan=true" >>"$GITHUB_OUTPUT"
          trusted_workspace="$RUNNER_TEMP/trusted-workspace"
          mkdir -p "$trusted_workspace"
          git init -q "$trusted_workspace"
          gh auth setup-git
          git -C "$trusted_workspace" remote add origin "$GITHUB_SERVER_URL/$REPOSITORY.git"
          git -C "$trusted_workspace" fetch --no-tags --depth=1 origin "$live_base_sha"
          git -C "$trusted_workspace" checkout --detach --quiet "$live_base_sha"
          git -C "$trusted_workspace" cat-file -e "$live_base_sha^{commit}"
          echo "TRUSTED_WORKSPACE=$trusted_workspace" >> "$GITHUB_ENV"

'''
if validation_step.count("Validate repository dispatch against live pull request metadata") != 1:
    raise SystemExit("unexpected validation-step shape")
visibility_index = text.index(visibility_marker)
text = text[:visibility_index] + repaired_validation + text[visibility_index:]

old_fetch = "      - name: Fetch pull request head for trusted scan\n        if: github.event_name == 'pull_request_target' || github.event.client_payload.pr_number != ''\n"
new_fetch = "      - name: Fetch pull request head for trusted scan\n        if: >-\n          steps.dispatch_validation.outputs.should_scan != 'false'\n          && (github.event_name == 'pull_request_target' || github.event.client_payload.pr_number != '')\n"
if text.count(old_fetch) != 1:
    raise SystemExit("fetch-head step shape drifted")
text = text.replace(old_fetch, new_fetch, 1)

old_self_test = "      - name: Self-test Strix required workflow contract\n        timeout-minutes: 2\n"
new_self_test = "      - name: Self-test Strix required workflow contract\n        if: steps.dispatch_validation.outputs.should_scan != 'false'\n        timeout-minutes: 2\n"
if text.count(old_self_test) != 1:
    raise SystemExit("self-test step shape drifted")
text = text.replace(old_self_test, new_self_test, 1)

old_gate = "      - name: Gate Strix secrets\n        id: gate\n"
new_gate = "      - name: Gate Strix secrets\n        if: steps.dispatch_validation.outputs.should_scan != 'false'\n        id: gate\n"
if text.count(old_gate) != 1:
    raise SystemExit("gate step shape drifted")
text = text.replace(old_gate, new_gate, 1)

old_publish = "        if: ${{ always() && !cancelled() && github.event_name == 'repository_dispatch' && github.event.client_payload.pr_head_sha != '' }}\n"
new_publish = "        if: ${{ always() && !cancelled() && steps.dispatch_validation.outputs.should_scan != 'false' && github.event_name == 'repository_dispatch' && github.event.client_payload.pr_head_sha != '' }}\n"
if text.count(old_publish) != 1:
    raise SystemExit("manual-status publication step shape drifted")
text = text.replace(old_publish, new_publish, 1)

workflow_path.write_text(text, encoding="utf-8")
