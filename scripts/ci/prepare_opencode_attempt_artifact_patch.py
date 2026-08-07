#!/usr/bin/env python3
"""Materialize the reviewed current-attempt OpenCode artifact identity repair.

This helper is temporary branch-local tooling. It patches only the permanent
OpenCode dispatch workflow, authoritative doctoring, and the Unreleased
changelog entry. The publishing workflow removes this file before committing
the verified implementation.
"""

from __future__ import annotations

from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/opencode-review-dispatch.yml")
DOCTORING_PATH = Path("docs/doctoring/opencode-coverage-artifact-reruns.md")
CHANGELOG_PATH = Path("CHANGELOG.md")


def action_expression(value: str) -> str:
    """Return a literal GitHub Actions expression without early evaluation."""
    return "$" + "{{ " + value + " }}"


def unique_index(
    lines: list[str],
    needle: str,
    *,
    start: int = 0,
    end: int | None = None,
    label: str,
) -> int:
    """Return the only exact line match within a bounded line range."""
    stop = len(lines) if end is None else end
    matches = [index for index in range(start, stop) if lines[index] == needle]
    if len(matches) != 1:
        raise SystemExit(f"Expected exactly one {label}, found {len(matches)}.")
    return matches[0]


def patch_workflow() -> None:
    """Bind exact artifact selection to producer-attested current-run provenance."""
    lines = WORKFLOW_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    producer_start = unique_index(
        lines, "  coverage-source-tree:\n", label="coverage source job"
    )
    consumer_start = unique_index(
        lines, "  coverage-evidence:\n", label="coverage evidence job"
    )

    artifact_output = (
        "      coverage_source_artifact_id: "
        + action_expression("steps.coverage_source_upload.outputs.artifact-id")
        + "\n"
    )
    artifact_output_index = unique_index(
        lines,
        artifact_output,
        start=producer_start,
        end=consumer_start,
        label="coverage artifact ID job output",
    )
    attempt_output = (
        "      coverage_source_run_attempt: "
        + action_expression("steps.coverage_source_attempt.outputs.run_attempt")
        + "\n"
    )
    if attempt_output in lines[producer_start:consumer_start]:
        raise SystemExit("Producer attempt output unexpectedly already exists.")
    lines.insert(artifact_output_index + 1, attempt_output)

    producer_start = unique_index(
        lines, "  coverage-source-tree:\n", label="coverage source job after output"
    )
    consumer_start = unique_index(
        lines,
        "  coverage-evidence:\n",
        label="coverage evidence job after output",
    )
    upload_step_index = unique_index(
        lines,
        "      - name: Upload materialized pull request merge tree\n",
        start=producer_start,
        end=consumer_start,
        label="coverage source upload step",
    )
    if "        id: coverage_source_attempt\n" in lines[producer_start:consumer_start]:
        raise SystemExit("Producer attempt attestation step unexpectedly already exists.")
    attempt_step = [
        "      - name: Record coverage source workflow attempt\n",
        "        id: coverage_source_attempt\n",
        "        env:\n",
        "          GITHUB_RUN_ATTEMPT: "
        + action_expression("github.run_attempt")
        + "\n",
        "        shell: bash --noprofile --norc -e -o pipefail {0}\n",
        "        run: |\n",
        "          if ! [[ \"$GITHUB_RUN_ATTEMPT\" =~ ^[1-9][0-9]*$ ]]; then\n",
        "            echo \"::error::Coverage producer workflow attempt is not a positive integer.\"\n",
        "            exit 1\n",
        "          fi\n",
        "          printf 'run_attempt=%s\\n' \"$GITHUB_RUN_ATTEMPT\" >>\"$GITHUB_OUTPUT\"\n",
        "\n",
    ]
    lines[upload_step_index:upload_step_index] = attempt_step

    consumer_start = unique_index(
        lines,
        "  coverage-evidence:\n",
        label="coverage evidence job before identity guard",
    )
    review_start = unique_index(
        lines,
        "  opencode-review-target:\n",
        start=consumer_start,
        label="OpenCode review target job",
    )
    download_step_index = unique_index(
        lines,
        "      - name: Download current-attempt materialized pull request merge tree\n",
        start=consumer_start,
        end=review_start,
        label="coverage source download step",
    )
    if "        id: coverage_source_identity\n" in lines[consumer_start:review_start]:
        raise SystemExit("Coverage source identity step unexpectedly already exists.")

    identity_step = [
        "      - name: Verify coverage source identity for current workflow attempt\n",
        "        id: coverage_source_identity\n",
        "        continue-on-error: true\n",
        "        env:\n",
        "          COVERAGE_SOURCE_ARTIFACT_ID: "
        + action_expression(
            "needs.coverage-source-tree.outputs.coverage_source_artifact_id"
        )
        + "\n",
        "          COVERAGE_SOURCE_RUN_ATTEMPT: "
        + action_expression(
            "needs.coverage-source-tree.outputs.coverage_source_run_attempt"
        )
        + "\n",
        "          CURRENT_RUN_ATTEMPT: "
        + action_expression("github.run_attempt")
        + "\n",
        "        shell: bash --noprofile --norc -e -o pipefail {0}\n",
        "        run: |\n",
        "          if ! [[ \"$COVERAGE_SOURCE_ARTIFACT_ID\" =~ ^[1-9][0-9]*$ ]] || \\\n",
        "            ! [[ \"$CURRENT_RUN_ATTEMPT\" =~ ^[1-9][0-9]*$ ]] || \\\n",
        "            [ \"$COVERAGE_SOURCE_RUN_ATTEMPT\" != \"$CURRENT_RUN_ATTEMPT\" ]; then\n",
        "            echo \"::error::Coverage source identity is invalid for current workflow attempt ${CURRENT_RUN_ATTEMPT:-missing}; producer attempt=${COVERAGE_SOURCE_RUN_ATTEMPT:-missing}, artifact_id=${COVERAGE_SOURCE_ARTIFACT_ID:-missing}.\"\n",
        "            exit 1\n",
        "          fi\n",
        "          printf 'artifact_id=%s\\n' \"$COVERAGE_SOURCE_ARTIFACT_ID\" >>\"$GITHUB_OUTPUT\"\n",
        "\n",
    ]
    lines[download_step_index:download_step_index] = identity_step

    consumer_start = unique_index(
        lines,
        "  coverage-evidence:\n",
        label="coverage evidence job before download binding",
    )
    review_start = unique_index(
        lines,
        "  opencode-review-target:\n",
        start=consumer_start,
        label="OpenCode review target job after identity insertion",
    )
    download_step_index = unique_index(
        lines,
        "      - name: Download current-attempt materialized pull request merge tree\n",
        start=consumer_start,
        end=review_start,
        label="coverage source download after identity insertion",
    )
    if lines[download_step_index + 1] != "        id: coverage_source_download\n":
        raise SystemExit("Coverage source download ID anchor changed.")
    lines.insert(
        download_step_index + 1,
        "        if: steps.coverage_source_identity.outcome == 'success'\n",
    )

    artifact_ids_index = unique_index(
        lines,
        "          artifact-ids: "
        + action_expression(
            "needs.coverage-source-tree.outputs.coverage_source_artifact_id"
        )
        + "\n",
        start=download_step_index,
        end=review_start,
        label="direct producer artifact ID download binding",
    )
    lines[artifact_ids_index] = (
        "          artifact-ids: "
        + action_expression("steps.coverage_source_identity.outputs.artifact_id")
        + "\n"
    )

    missing_report_index = unique_index(
        lines,
        "      - name: Report missing current-attempt coverage source\n",
        start=download_step_index,
        end=review_start,
        label="missing coverage source report",
    )
    missing_if_index = unique_index(
        lines,
        "        if: steps.coverage_source_download.outcome != 'success'\n",
        start=missing_report_index,
        end=review_start,
        label="missing coverage source condition",
    )
    lines[missing_if_index] = (
        "        if: steps.coverage_source_identity.outcome == 'success' && "
        "steps.coverage_source_download.outcome != 'success'\n"
    )

    identity_report = [
        "      - name: Report coverage source identity failure\n",
        "        if: steps.coverage_source_identity.outcome != 'success'\n",
        "        env:\n",
        "          GITHUB_RUN_ATTEMPT: "
        + action_expression("github.run_attempt")
        + "\n",
        "        run: |\n",
        "          set -euo pipefail\n",
        "          echo \"::error::Coverage source evidence was not produced and identified in current workflow run attempt ${GITHUB_RUN_ATTEMPT}; a failed-jobs-only rerun cannot reuse prior-attempt source evidence.\"\n",
        "          echo \"::error::Use a full rerun or a fresh repository dispatch so coverage-source-tree runs and uploads exact current-attempt evidence.\"\n",
        "          exit 1\n",
        "\n",
    ]
    lines[download_step_index:download_step_index] = identity_report

    WORKFLOW_PATH.write_text("".join(lines), encoding="utf-8")


def patch_doctoring() -> None:
    """Document immutability, attempt provenance, and bounded identifier checks."""
    doctoring = DOCTORING_PATH.read_text(encoding="utf-8")
    decision_anchor = "The source artifact retains the existing one-day retention period. "
    decision_insert = (
        "The producer records its literal workflow attempt in a step output. Before any "
        "download, the credential-free consumer verifies that the artifact ID is a positive "
        "integer and that the producer-attested attempt equals the consumer's current "
        "`github.run_attempt`. Artifact immutability identifies one upload; the separate "
        "attempt attestation proves when its producer executed.\n\n"
        + decision_anchor
    )
    if doctoring.count(decision_anchor) != 1:
        raise SystemExit("Doctoring decision anchor changed.")
    doctoring = doctoring.replace(decision_anchor, decision_insert, 1)

    bullet_anchor = (
        "- The upload step exports the immutable `artifact-id`; the consumer downloads "
        "with `artifact-ids` rather than `name`.\n"
    )
    bullet_insert = bullet_anchor + (
        "- The producer exports its step-recorded run attempt; the consumer validates both "
        "the artifact identifier and attempt marker before exposing the identifier to the "
        "download action. Empty, malformed, or prior-attempt values fail closed.\n"
    )
    if doctoring.count(bullet_anchor) != 1:
        raise SystemExit("Doctoring contract bullet anchor changed.")
    doctoring = doctoring.replace(bullet_anchor, bullet_insert, 1)

    table_old = (
        "| Failed-jobs-only rerun while producer is omitted | No current-attempt producer "
        "output exists | Fails closed with recovery guidance | Expected failure |"
    )
    table_new = (
        "| Failed-jobs-only rerun while producer is omitted | Producer attempt marker is "
        "missing or belongs to an earlier attempt | Rejects identity before artifact "
        "download | Expected failure |"
    )
    if doctoring.count(table_old) != 1:
        raise SystemExit("Doctoring rerun table anchor changed.")
    doctoring = doctoring.replace(table_old, table_new, 1)

    rationale_anchor = (
        "The producer's exact `artifact-id` closes that ambiguity. Attempt-qualified naming "
        "remains useful for diagnostics, while ID-based selection is the authoritative "
        "binding.\n"
    )
    rationale_new = (
        "The producer's exact `artifact-id` closes upload-selection ambiguity, while its "
        "step-recorded attempt closes execution-attempt ambiguity. Attempt-qualified names "
        "remain diagnostic; a validated positive artifact ID and producer-attempt equality "
        "are both required before download.\n"
    )
    if doctoring.count(rationale_anchor) != 1:
        raise SystemExit("Doctoring rationale anchor changed.")
    doctoring = doctoring.replace(rationale_anchor, rationale_new, 1)

    verification_old = (
        "1. attempt-scoped artifact naming and immutable `artifact-id` producer output;\n"
        "2. exact-ID download by the consumer;\n"
        "3. actionable failure for a missing current-attempt artifact;\n"
        "4. one-day retention; and\n"
        "5. absence of repository, OIDC, secret, and review-write credentials from `coverage-evidence`.\n"
    )
    verification_new = (
        "1. attempt-scoped artifact naming and immutable `artifact-id` producer output;\n"
        "2. producer-attested attempt output and pre-download current-attempt equality;\n"
        "3. positive-integer artifact ID validation and exact-ID download;\n"
        "4. actionable failure for missing, malformed, or prior-attempt evidence;\n"
        "5. one-day retention; and\n"
        "6. absence of repository, OIDC, secret, and review-write credentials from `coverage-evidence`.\n"
    )
    if doctoring.count(verification_old) != 1:
        raise SystemExit("Doctoring verification anchor changed.")
    DOCTORING_PATH.write_text(
        doctoring.replace(verification_old, verification_new, 1),
        encoding="utf-8",
    )


def patch_changelog() -> None:
    """Record the complete identity and provenance gate in Unreleased fixes."""
    changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    old_entry = (
        "- Bound OpenCode coverage source artifacts to one workflow attempt and immutable "
        "artifact ID, retained one-day source evidence, and made failed-jobs-only reruns "
        "fail closed with full-rerun or fresh-dispatch guidance instead of searching for "
        "expired or prior-attempt artifacts.\n"
    )
    new_entry = (
        "- Bound OpenCode coverage source evidence to a validated immutable artifact ID and "
        "producer-attested workflow attempt, retained one-day source evidence, and made "
        "selective reruns fail closed before download on missing, malformed, or prior-attempt "
        "identity with full-rerun or fresh-dispatch guidance.\n"
    )
    if changelog.count(old_entry) != 1:
        raise SystemExit("CHANGELOG attempt-artifact entry anchor changed.")
    CHANGELOG_PATH.write_text(
        changelog.replace(old_entry, new_entry, 1), encoding="utf-8"
    )


def main() -> None:
    """Apply the bounded workflow, doctoring, and changelog repair."""
    patch_workflow()
    patch_doctoring()
    patch_changelog()


if __name__ == "__main__":
    main()
