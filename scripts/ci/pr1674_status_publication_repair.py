#!/usr/bin/env python3
"""Materialize PR #1674 Strix live-publication authority on the existing writer branch.

The transformer is deliberately exact-anchor based. It refuses drift rather than
silently rewriting concurrent workflow changes. The temporary driver and its
workflow are removed from the prepared tree before publication.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/strix.yml"
TEST = ROOT / "tests/test_strix_repository_dispatch_live_state.py"
SELF = ROOT / "scripts/ci/pr1674_status_publication_repair.py"
TEMP_WORKFLOW = ROOT / ".github/workflows/_temp_pr1674_status_publication_repair.yml"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact anchor or fail closed on drift/ambiguity."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


FRESH_TOKEN_STEP = r'''      - name: Refresh OpenCode app token for Strix status revalidation
        id: status_target_app_token
        if: ${{ always() && !cancelled() && steps.dispatch_validation.outputs.should_scan != 'false' && github.event_name == 'repository_dispatch' && github.event.client_payload.pr_head_sha != '' }}
        env:
          OIDC_AUDIENCE: opencode-github-action
          OPENCODE_API_BASE_URL: https://api.opencode.ai
        run: |
          set -euo pipefail
          mark_unavailable() {
            echo "available=false" >>"$GITHUB_OUTPUT"
          }
          if [ -z "${ACTIONS_ID_TOKEN_REQUEST_TOKEN:-}" ] || [ -z "${ACTIONS_ID_TOKEN_REQUEST_URL:-}" ]; then
            echo "Strix status revalidation app token unavailable: OIDC request environment is missing."
            mark_unavailable
            exit 0
          fi
          request_url="${ACTIONS_ID_TOKEN_REQUEST_URL}"
          separator="&"
          case "$request_url" in
            *\?*) ;;
            *) separator="?" ;;
          esac
          if ! oidc_response="$(curl -fsS -H "Authorization: Bearer ${ACTIONS_ID_TOKEN_REQUEST_TOKEN}" "${request_url}${separator}audience=${OIDC_AUDIENCE}")"; then
            echo "Strix status revalidation app token unavailable: OIDC request failed."
            mark_unavailable
            exit 0
          fi
          oidc_token="$(jq -r '.value // empty' <<<"$oidc_response")"
          if [ -z "$oidc_token" ]; then
            echo "Strix status revalidation app token unavailable: OIDC response was empty."
            mark_unavailable
            exit 0
          fi
          if ! token_response="$(curl -fsS -X POST -H "Authorization: Bearer ${oidc_token}" "${OPENCODE_API_BASE_URL}/exchange_github_app_token")"; then
            echo "Strix status revalidation app token unavailable: app-token exchange failed."
            mark_unavailable
            exit 0
          fi
          app_token="$(jq -r '.token // empty' <<<"$token_response")"
          if [ -z "$app_token" ]; then
            echo "Strix status revalidation app token unavailable: exchange response was empty."
            mark_unavailable
            exit 0
          fi
          echo "::add-mask::$app_token"
          {
            echo "available=true"
            echo "token=$app_token"
          } >>"$GITHUB_OUTPUT"

'''

LIVE_REVALIDATION_RUN = r'''          set -euo pipefail
          if ! [[ "$REPOSITORY" =~ ^ContextualWisdomLab/[A-Za-z0-9_.-]+$ ]] ||
            ! [[ "$PR_NUMBER" =~ ^[1-9][0-9]*$ ]] ||
            ! [[ "$EXPECTED_HEAD_SHA" =~ ^[0-9a-fA-F]{40}$ ]]; then
            echo "::error::Strix publication revalidation metadata is malformed."
            exit 1
          fi
          if ! pull_request_json="$(gh api "repos/${REPOSITORY}/pulls/${PR_NUMBER}")"; then
            echo "::error::Could not revalidate live Strix pull request before status publication."
            exit 1
          fi
          live_state="$(jq -r '.state // empty' <<<"$pull_request_json")"
          live_draft="$(jq -r 'if .draft == true then "true" elif .draft == false then "false" else empty end' <<<"$pull_request_json")"
          live_base_repository="$(jq -r '.base.repo.full_name // empty' <<<"$pull_request_json")"
          live_head_sha="$(jq -r '.head.sha // empty' <<<"$pull_request_json")"
          if [ -z "$live_state" ] || [ -z "$live_draft" ] ||
            [ "$live_base_repository" != "$REPOSITORY" ] || [ -z "$live_head_sha" ]; then
            printf '::error::Strix publication target is unverifiable for %s#%s. state=%s draft=%s base_repo=%s head=%s.\n' \
              "$REPOSITORY" "$PR_NUMBER" "${live_state:-missing}" "${live_draft:-missing}" \
              "${live_base_repository:-missing}" "${live_head_sha:-missing}"
            exit 1
          fi
          if [ "$live_head_sha" != "$EXPECTED_HEAD_SHA" ]; then
            printf '::error::Strix publication target head moved for %s#%s: expected=%s live=%s.\n' \
              "$REPOSITORY" "$PR_NUMBER" "$EXPECTED_HEAD_SHA" "$live_head_sha"
            exit 1
          fi
          if [ "$live_state" = "closed" ] || { [ "$live_state" = "open" ] && [ "$live_draft" = "true" ]; }; then
            echo "publish_status=false" >>"$GITHUB_OUTPUT"
            printf '::notice::Strix publication suppressed for exact-head non-reviewable target %s#%s state=%s draft=%s.\n' \
              "$REPOSITORY" "$PR_NUMBER" "$live_state" "$live_draft"
            exit 0
          fi
          if [ "$live_state" != "open" ] || [ "$live_draft" != "false" ]; then
            printf '::error::Strix publication target has unexpected live state for %s#%s: state=%s draft=%s.\n' \
              "$REPOSITORY" "$PR_NUMBER" "$live_state" "$live_draft"
            exit 1
          fi
          echo "publish_status=true" >>"$GITHUB_OUTPUT"
'''

SCAN_REVALIDATION_STEP = r'''      - name: Revalidate repository dispatch before status publication
        id: dispatch_publish_validation
        if: ${{ always() && !cancelled() && steps.dispatch_validation.outputs.should_scan != 'false' && github.event_name == 'repository_dispatch' && github.event.client_payload.pr_head_sha != '' }}
        env:
          GH_TOKEN: ${{ steps.status_target_app_token.outputs.token || secrets.OPENCODE_APPROVE_TOKEN || github.token }}
          REPOSITORY: ${{ github.event.client_payload.target_repository }}
          PR_NUMBER: ${{ github.event.client_payload.pr_number }}
          EXPECTED_HEAD_SHA: ${{ github.event.client_payload.pr_head_sha }}
        run: |
''' + LIVE_REVALIDATION_RUN + "\n"

FOLLOWUP_REVALIDATION_STEP = r'''      - name: Revalidate repository dispatch before follow-up status publication
        id: followup_publish_validation
        env:
          GH_TOKEN: ${{ steps.target_app_token.outputs.token || secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN || github.token }}
          REPOSITORY: ${{ github.event.client_payload.target_repository }}
          PR_NUMBER: ${{ github.event.client_payload.pr_number }}
          EXPECTED_HEAD_SHA: ${{ github.event.client_payload.pr_head_sha }}
        run: |
''' + LIVE_REVALIDATION_RUN + "\n"


def repair_workflow(text: str) -> str:
    """Apply late-bound Strix authority and skip propagation without gate weakening."""
    text = replace_once(
        text,
        "    outputs:\n      should_scan: ${{ steps.dispatch_validation.outputs.should_scan }}\n",
        "    outputs:\n      should_scan: ${{ steps.dispatch_validation.outputs.should_scan }}\n"
        "      publish_status: ${{ steps.dispatch_publish_validation.outputs.publish_status }}\n",
        "strix job outputs",
    )
    text = replace_once(
        text,
        "      - name: Resolve target repository visibility\n        id: target_visibility\n        env:\n",
        "      - name: Resolve target repository visibility\n        id: target_visibility\n"
        "        if: github.event_name != 'repository_dispatch' || steps.dispatch_validation.outputs.should_scan != 'false'\n"
        "        env:\n",
        "target visibility skip guard",
    )

    scan_publish_anchor = (
        "      - name: Publish same-head manual Strix status\n"
        "        if: ${{ always() && !cancelled() && steps.dispatch_validation.outputs.should_scan != 'false' && github.event_name == 'repository_dispatch' && github.event.client_payload.pr_head_sha != '' }}\n"
    )
    text = replace_once(
        text,
        scan_publish_anchor,
        FRESH_TOKEN_STEP
        + SCAN_REVALIDATION_STEP
        + "      - name: Publish same-head manual Strix status\n"
        + "        if: ${{ always() && !cancelled() && steps.dispatch_publish_validation.outputs.publish_status == 'true' && github.event_name == 'repository_dispatch' && github.event.client_payload.pr_head_sha != '' }}\n",
        "scan status publication boundary",
    )
    text = replace_once(
        text,
        "          TARGET_APP_STATUS_TOKEN: ${{ steps.target_app_token.outputs.token || '' }}\n",
        "          TARGET_APP_STATUS_TOKEN: ${{ steps.status_target_app_token.outputs.token || '' }}\n",
        "scan publisher fresh app token",
    )
    text = replace_once(
        text,
        "    if: ${{ always() && !cancelled() && needs.strix.outputs.should_scan == 'true' && github.event_name == 'repository_dispatch' && github.event.client_payload.pr_head_sha != '' }}\n",
        "    if: ${{ always() && !cancelled() && needs.strix.outputs.should_scan == 'true' && needs.strix.outputs.publish_status == 'true' && github.event_name == 'repository_dispatch' && github.event.client_payload.pr_head_sha != '' }}\n",
        "follow-up job live authority condition",
    )
    text = replace_once(
        text,
        "    permissions:\n      id-token: write\n      statuses: write # Required for downscoped OIDC status publication.\n",
        "    permissions:\n      id-token: write\n      pull-requests: read\n      statuses: write # Required for downscoped OIDC status publication.\n",
        "follow-up live PR read permission",
    )
    followup_publish_anchor = (
        "      - name: Publish same-head manual Strix status\n"
        "        env:\n"
        "          TARGET_APP_STATUS_TOKEN: ${{ steps.target_app_token.outputs.token || '' }}\n"
    )
    text = replace_once(
        text,
        followup_publish_anchor,
        FOLLOWUP_REVALIDATION_STEP
        + "      - name: Publish same-head manual Strix status\n"
        + "        if: steps.followup_publish_validation.outputs.publish_status == 'true'\n"
        + "        env:\n"
        + "          TARGET_APP_STATUS_TOKEN: ${{ steps.target_app_token.outputs.token || '' }}\n",
        "follow-up late publication boundary",
    )
    return text


def repair_test(text: str) -> str:
    """Extend the existing executable contract to cover the follow-up job boundary."""
    anchor = (
        "    status_condition = str(status_job.get(\"if\", \"\"))\n"
        "    assert \"needs.strix.outputs.should_scan == 'true'\" in status_condition\n"
        "    assert \"needs.strix.outputs.publish_status == 'true'\" in status_condition\n"
        "    assert \"github.event_name == 'repository_dispatch'\" in status_condition\n"
    )
    replacement = anchor + (
        "\n    status_steps = status_job[\"steps\"]\n"
        "    followup_validation = next(\n"
        "        step for step in status_steps\n"
        "        if step.get(\"name\") == \"Revalidate repository dispatch before follow-up status publication\"\n"
        "    )\n"
        "    assert followup_validation.get(\"id\") == \"followup_publish_validation\"\n"
        "    assert str(followup_validation.get(\"run\")) == str(\n"
        "        _step(\"Revalidate repository dispatch before status publication\").get(\"run\")\n"
        "    )\n"
        "    followup_token = str(followup_validation.get(\"env\", {}).get(\"GH_TOKEN\", \"\"))\n"
        "    assert \"target_app_token.outputs.token\" in followup_token\n"
        "    followup_publish = next(\n"
        "        step for step in status_steps if step.get(\"name\") == \"Publish same-head manual Strix status\"\n"
        "    )\n"
        "    assert \"steps.followup_publish_validation.outputs.publish_status == 'true'\" in str(\n"
        "        followup_publish.get(\"if\", \"\")\n"
        "    )\n"
    )
    return replace_once(text, anchor, replacement, "follow-up status regression")


def assert_contract(workflow: str, tests: str) -> None:
    """Perform dependency-free structural checks before exact-head CI takes over."""
    required = {
        "visibility skip guard": "steps.dispatch_validation.outputs.should_scan != 'false'",
        "late scan token": "id: status_target_app_token",
        "late scan validation": "id: dispatch_publish_validation",
        "late scan decision": "publish_status: ${{ steps.dispatch_publish_validation.outputs.publish_status }}",
        "follow-up validation": "id: followup_publish_validation",
        "follow-up decision": "needs.strix.outputs.publish_status == 'true'",
        "follow-up publish guard": "steps.followup_publish_validation.outputs.publish_status == 'true'",
    }
    for label, needle in required.items():
        if needle not in workflow:
            raise RuntimeError(f"missing {label}: {needle}")
    if "test_repository_dispatch_revalidates_live_state_again_before_status_publication" not in tests:
        raise RuntimeError("existing executable status revalidation regression disappeared")
    if "followup_publish_validation" not in tests:
        raise RuntimeError("follow-up publication boundary lacks regression coverage")


def main() -> int:
    """Materialize the source/test repair and remove this one-shot machinery."""
    workflow = repair_workflow(WORKFLOW.read_text(encoding="utf-8"))
    tests = repair_test(TEST.read_text(encoding="utf-8"))
    assert_contract(workflow, tests)
    WORKFLOW.write_text(workflow, encoding="utf-8")
    TEST.write_text(tests, encoding="utf-8")
    SELF.unlink()
    TEMP_WORKFLOW.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
