"""One-shot deterministic source transform for PR #1588.

The red exact-head regression already exists on the PR. This script only
materializes that tested contract into the workflow and is deleted by the
one-shot writer in the same source-fix commit.
"""

from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/strix.yml")
TEST_PATH = Path("tests/test_strix_control_plane_supersession.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one exact match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    tests = TEST_PATH.read_text(encoding="utf-8")

    workflow = replace_once(
        workflow,
        """    permissions:\n      actions: read\n      contents: read\n      id-token: write\n      models: read\n      statuses: write\n""",
        """    permissions:\n      actions: read\n      contents: read\n      id-token: write\n      models: read\n      pull-requests: read\n      statuses: write\n""",
        "strix job permissions",
    )

    harden = """      - name: Harden runner\n        uses: step-security/harden-runner@b09bb98e06d4d774595224525879c09bc6e98c40 # v2.20.1\n        with:\n          egress-policy: audit\n          disable-file-monitoring: true\n\n"""
    early = """      - name: Validate live pull request before Strix setup\n        if: github.event_name == 'pull_request_target'\n        env:\n          GH_TOKEN: ${{ github.token }}\n          TARGET_REPOSITORY: ${{ github.event.pull_request.base.repo.full_name }}\n          PR_NUMBER: ${{ github.event.pull_request.number }}\n          EXPECTED_HEAD_SHA: ${{ github.event.pull_request.head.sha }}\n        run: |\n          set -euo pipefail\n          if ! pull_request_json=\"$(gh api \"repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}\")\"; then\n            echo \"::error::Unable to revalidate live pull request before Strix setup.\"\n            exit 1\n          fi\n          live_state=\"$(jq -r '.state // empty' <<<\"$pull_request_json\")\"\n          live_head_sha=\"$(jq -r '.head.sha // empty' <<<\"$pull_request_json\")\"\n          if [ \"$live_state\" != \"open\" ] || [ \"$live_head_sha\" != \"$EXPECTED_HEAD_SHA\" ]; then\n            echo \"::error::Strix event is stale or the pull request is no longer open before setup.\"\n            exit 1\n          fi\n\n"""
    workflow = replace_once(workflow, harden, harden + early, "early validation")

    provider = "      - name: Provision contextual-orchestrator Strix sidecar\n"
    provider_check = """      - name: Revalidate live pull request before provider execution\n        if: github.event_name == 'pull_request_target'\n        env:\n          GH_TOKEN: ${{ github.token }}\n          TARGET_REPOSITORY: ${{ github.event.pull_request.base.repo.full_name }}\n          PR_NUMBER: ${{ github.event.pull_request.number }}\n          EXPECTED_HEAD_SHA: ${{ github.event.pull_request.head.sha }}\n        run: |\n          set -euo pipefail\n          if ! pull_request_json=\"$(gh api \"repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}\")\"; then\n            echo \"::error::Unable to revalidate live pull request before provider execution.\"\n            exit 1\n          fi\n          live_state=\"$(jq -r '.state // empty' <<<\"$pull_request_json\")\"\n          live_head_sha=\"$(jq -r '.head.sha // empty' <<<\"$pull_request_json\")\"\n          if [ \"$live_state\" != \"open\" ] || [ \"$live_head_sha\" != \"$EXPECTED_HEAD_SHA\" ]; then\n            echo \"::error::Strix event is stale or the pull request is no longer open before provider execution.\"\n            exit 1\n          fi\n\n"""
    workflow = replace_once(workflow, provider, provider_check + provider, "provider validation")

    collect = "      - name: Collect Strix reports for artifact upload\n"
    publication_check = """      - name: Revalidate live pull request before evidence publication\n        id: publication_revalidation\n        if: ${{ always() && github.event_name == 'pull_request_target' }}\n        env:\n          GH_TOKEN: ${{ github.token }}\n          TARGET_REPOSITORY: ${{ github.event.pull_request.base.repo.full_name }}\n          PR_NUMBER: ${{ github.event.pull_request.number }}\n          EXPECTED_HEAD_SHA: ${{ github.event.pull_request.head.sha }}\n        run: |\n          set -euo pipefail\n          if ! pull_request_json=\"$(gh api \"repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}\")\"; then\n            echo \"::error::Unable to revalidate live pull request before evidence publication.\"\n            exit 1\n          fi\n          live_state=\"$(jq -r '.state // empty' <<<\"$pull_request_json\")\"\n          live_head_sha=\"$(jq -r '.head.sha // empty' <<<\"$pull_request_json\")\"\n          if [ \"$live_state\" != \"open\" ] || [ \"$live_head_sha\" != \"$EXPECTED_HEAD_SHA\" ]; then\n            echo \"::error::Strix event is stale or the pull request is no longer open before evidence publication.\"\n            exit 1\n          fi\n          echo \"valid=true\" >> \"$GITHUB_OUTPUT\"\n\n"""
    workflow = replace_once(workflow, collect, publication_check + collect, "publication validation")

    workflow = replace_once(
        workflow,
        """      - name: Collect Strix reports for artifact upload\n        if: ${{ always() && steps.gate.outputs.enabled == 'true' }}\n""",
        """      - name: Collect Strix reports for artifact upload\n        if: ${{ always() && steps.gate.outputs.enabled == 'true' && (github.event_name != 'pull_request_target' || steps.publication_revalidation.outputs.valid == 'true') }}\n""",
        "report collection gate",
    )
    workflow = replace_once(
        workflow,
        """      - name: Upload Strix reports artifact\n        if: ${{ always() && steps.gate.outputs.enabled == 'true' }}\n""",
        """      - name: Upload Strix reports artifact\n        if: ${{ always() && steps.gate.outputs.enabled == 'true' && (github.event_name != 'pull_request_target' || steps.publication_revalidation.outputs.valid == 'true') }}\n""",
        "artifact upload gate",
    )

    tests = replace_once(
        tests,
        '    assert "GH_TOKEN: ${{ github.token }}" in early\n',
        '    assert "GH_TOKEN: ${{ github.token }}" in early\n'
        '    assert "pull-requests: read" in workflow.split("  strix:", 1)[1].split("    steps:", 1)[0]\n'
        '    assert "if ! pull_request_json=" in early\n',
        "private-repo lookup regression",
    )
    tests = replace_once(
        tests,
        '    assert "exit 1" in recheck\n\n\ndef test_strix_preserves_provider_serialization_and_timeout_repair()',
        '    assert "exit 1" in recheck\n'
        '    assert "id: publication_revalidation" in recheck\n'
        '    assert "always() && github.event_name == \'pull_request_target\'" in recheck\n'
        '    collect = _step(workflow, "Collect Strix reports for artifact upload")\n'
        '    upload = _step(workflow, "Upload Strix reports artifact")\n'
        '    assert "steps.publication_revalidation.outputs.valid == \'true\'" in collect\n'
        '    assert "steps.publication_revalidation.outputs.valid == \'true\'" in upload\n\n\n'
        'def test_strix_preserves_provider_serialization_and_timeout_repair()',
        "publication gating regression",
    )

    WORKFLOW_PATH.write_text(workflow, encoding="utf-8")
    TEST_PATH.write_text(tests, encoding="utf-8")


if __name__ == "__main__":
    main()
