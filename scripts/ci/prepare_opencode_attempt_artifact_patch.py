#!/usr/bin/env python3
"""Materialize the current-attempt OpenCode artifact identity repair.

This helper is temporary branch-local tooling. The finalizer removes it before
publishing the verified permanent workflow, doctoring, and changelog changes.
"""

from __future__ import annotations

from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/opencode-review-dispatch.yml")
DOCTORING_PATH = Path("docs/doctoring/opencode-coverage-artifact-reruns.md")
CHANGELOG_PATH = Path("CHANGELOG.md")


def expression(value: str) -> str:
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
    """Return the sole exact line match inside the requested bounds."""
    stop = len(lines) if end is None else end
    matches = [index for index in range(start, stop) if lines[index] == needle]
    if len(matches) != 1:
        raise SystemExit(f"Expected one {label}, found {len(matches)}.")
    return matches[0]


def patch_workflow() -> None:
    """Require producer-attempt and artifact-ID identity before download."""
    lines = WORKFLOW_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    producer = unique_index(lines, "  coverage-source-tree:\n", label="producer job")
    consumer = unique_index(lines, "  coverage-evidence:\n", label="consumer job")

    artifact_output = (
        "      coverage_source_artifact_id: "
        + expression("steps.coverage_source_upload.outputs.artifact-id")
        + "\n"
    )
    output_index = unique_index(
        lines,
        artifact_output,
        start=producer,
        end=consumer,
        label="artifact ID output",
    )
    attempt_output = (
        "      coverage_source_run_attempt: "
        + expression("steps.coverage_source_attempt.outputs.run_attempt")
        + "\n"
    )
    if attempt_output in lines[producer:consumer]:
        raise SystemExit("Producer attempt output already exists.")
    lines.insert(output_index + 1, attempt_output)

    producer = unique_index(lines, "  coverage-source-tree:\n", label="producer job")
    consumer = unique_index(lines, "  coverage-evidence:\n", label="consumer job")
    upload = unique_index(
        lines,
        "      - name: Upload materialized pull request merge tree\n",
        start=producer,
        end=consumer,
        label="upload step",
    )
    if "        id: coverage_source_attempt\n" in lines[producer:consumer]:
        raise SystemExit("Producer attempt step already exists.")
    lines[upload:upload] = [
        "      - name: Record coverage source workflow attempt\n",
        "        id: coverage_source_attempt\n",
        "        env:\n",
        "          GITHUB_RUN_ATTEMPT: " + expression("github.run_attempt") + "\n",
        "        shell: bash --noprofile --norc -e -o pipefail {0}\n",
        "        run: |\n",
        "          if ! [[ \"$GITHUB_RUN_ATTEMPT\" =~ ^[1-9][0-9]*$ ]]; then\n",
        "            echo \"::error::Coverage producer workflow attempt is not a positive integer.\"\n",
        "            exit 1\n",
        "          fi\n",
        "          printf 'run_attempt=%s\\n' \"$GITHUB_RUN_ATTEMPT\" >>\"$GITHUB_OUTPUT\"\n",
        "\n",
    ]

    consumer = unique_index(lines, "  coverage-evidence:\n", label="consumer job")
    review = unique_index(
        lines,
        "  opencode-review-target:\n",
        start=consumer,
        label="review job",
    )
    download = unique_index(
        lines,
        "      - name: Download current-attempt materialized pull request merge tree\n",
        start=consumer,
        end=review,
        label="download step",
    )
    if "        id: coverage_source_identity\n" in lines[consumer:review]:
        raise SystemExit("Coverage source identity step already exists.")
    lines[download:download] = [
        "      - name: Verify coverage source identity for current workflow attempt\n",
        "        id: coverage_source_identity\n",
        "        continue-on-error: true\n",
        "        env:\n",
        "          COVERAGE_SOURCE_ARTIFACT_ID: "
        + expression("needs.coverage-source-tree.outputs.coverage_source_artifact_id")
        + "\n",
        "          COVERAGE_SOURCE_RUN_ATTEMPT: "
        + expression("needs.coverage-source-tree.outputs.coverage_source_run_attempt")
        + "\n",
        "          CURRENT_RUN_ATTEMPT: " + expression("github.run_attempt") + "\n",
        "        shell: bash --noprofile --norc -e -o pipefail {0}\n",
        "        run: |\n",
        "          if ! [[ \"$CURRENT_RUN_ATTEMPT\" =~ ^[1-9][0-9]*$ ]] || \\\n",
        "            [ \"$COVERAGE_SOURCE_RUN_ATTEMPT\" != \"$CURRENT_RUN_ATTEMPT\" ]; then\n",
        "            echo \"::error::Coverage source was not produced in current workflow attempt ${CURRENT_RUN_ATTEMPT:-missing}; producer attempt=${COVERAGE_SOURCE_RUN_ATTEMPT:-missing}.\"\n",
        "            echo \"::error::Use a full rerun or a fresh repository dispatch; failed-jobs-only reruns cannot reuse prior-attempt source evidence.\"\n",
        "            exit 1\n",
        "          fi\n",
        "          if ! [[ \"$COVERAGE_SOURCE_ARTIFACT_ID\" =~ ^[1-9][0-9]*$ ]]; then\n",
        "            echo \"::error::Coverage source artifact ID is missing or malformed for current workflow attempt.\"\n",
        "            echo \"::error::Use a full rerun or a fresh repository dispatch so the producer publishes current-attempt evidence.\"\n",
        "            exit 1\n",
        "          fi\n",
        "          artifact_id=$COVERAGE_SOURCE_ARTIFACT_ID\n",
        "          printf 'artifact_id=%s\\n' \"$artifact_id\" >>\"$GITHUB_OUTPUT\"\n",
        "\n",
    ]

    consumer = unique_index(lines, "  coverage-evidence:\n", label="consumer job")
    review = unique_index(lines, "  opencode-review-target:\n", start=consumer, label="review job")
    download = unique_index(
        lines,
        "      - name: Download current-attempt materialized pull request merge tree\n",
        start=consumer,
        end=review,
        label="download step after identity",
    )
    if lines[download + 1] != "        id: coverage_source_download\n":
        raise SystemExit("Download ID anchor changed.")
    lines.insert(download + 1, "        if: steps.coverage_source_identity.outcome == 'success'\n")

    direct_input = (
        "          artifact-ids: "
        + expression("needs.coverage-source-tree.outputs.coverage_source_artifact_id")
        + "\n"
    )
    direct_index = unique_index(
        lines,
        direct_input,
        start=download,
        end=review,
        label="direct artifact input",
    )
    lines[direct_index] = (
        "          artifact-ids: "
        + expression("steps.coverage_source_identity.outputs.artifact_id")
        + "\n"
    )

    report = unique_index(
        lines,
        "      - name: Report missing current-attempt coverage source\n",
        start=download,
        end=review,
        label="missing source report",
    )
    expected_if = "        if: steps.coverage_source_download.outcome != 'success'\n"
    if lines[report + 1] != expected_if:
        raise SystemExit("Missing source report condition changed.")
    lines[report + 1] = (
        "        if: steps.coverage_source_identity.outcome != 'success' || "
        "steps.coverage_source_download.outcome != 'success'\n"
    )
    WORKFLOW_PATH.write_text("".join(lines), encoding="utf-8")


def patch_doctoring() -> None:
    """Document artifact immutability separately from producer provenance."""
    text = DOCTORING_PATH.read_text(encoding="utf-8")
    anchor = "The source artifact retains the existing one-day retention period. "
    insertion = (
        "The producer also exports a step-recorded literal workflow attempt. Before "
        "download, the consumer verifies that this attempt equals its current "
        "`github.run_attempt` and that the immutable artifact ID is a positive decimal "
        "identifier. Artifact immutability selects one upload; attempt attestation proves "
        "that the producer executed in the current attempt.\n\n" + anchor
    )
    if text.count(anchor) != 1:
        raise SystemExit("Doctoring decision anchor changed.")
    text = text.replace(anchor, insertion, 1)

    bullet = (
        "- The upload step exports the immutable `artifact-id`; the consumer downloads "
        "with `artifact-ids` rather than `name`.\n"
    )
    replacement = (
        "- The upload step exports the immutable `artifact-id`; the consumer validates "
        "that it is a positive decimal identifier and passes only the validated step "
        "output to `download-artifact`.\n"
        "- The producer exports its step-recorded run attempt; the consumer rejects empty "
        "or prior-attempt provenance before download.\n"
    )
    if text.count(bullet) != 1:
        raise SystemExit("Doctoring contract bullet anchor changed.")
    text = text.replace(bullet, replacement, 1)

    table_old = (
        "| Failed-jobs-only rerun while producer is omitted | No current-attempt producer "
        "output exists | Fails closed with recovery guidance | Expected failure |"
    )
    table_new = (
        "| Failed-jobs-only rerun while producer is omitted | Producer attempt marker or "
        "artifact ID is missing or belongs to an earlier attempt | Rejects identity before "
        "download | Expected failure |"
    )
    if text.count(table_old) != 1:
        raise SystemExit("Doctoring rerun table anchor changed.")
    text = text.replace(table_old, table_new, 1)

    rationale_old = (
        "The producer's exact `artifact-id` closes that ambiguity. Attempt-qualified naming "
        "remains useful for diagnostics, while ID-based selection is the authoritative "
        "binding.\n"
    )
    rationale_new = (
        "The producer's exact `artifact-id` closes upload-selection ambiguity, while its "
        "step-recorded attempt closes execution-attempt ambiguity. The consumer validates "
        "both before download; attempt-qualified names remain diagnostic only.\n"
    )
    if text.count(rationale_old) != 1:
        raise SystemExit("Doctoring rationale anchor changed.")
    text = text.replace(rationale_old, rationale_new, 1)

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
        "3. positive-decimal artifact-ID validation and exact-ID download;\n"
        "4. actionable failure for missing, malformed, or prior-attempt evidence;\n"
        "5. one-day retention; and\n"
        "6. absence of repository, OIDC, secret, and review-write credentials from `coverage-evidence`.\n"
    )
    if text.count(verification_old) != 1:
        raise SystemExit("Doctoring verification anchor changed.")
    DOCTORING_PATH.write_text(
        text.replace(verification_old, verification_new, 1), encoding="utf-8"
    )


def patch_changelog() -> None:
    """Record current-attempt provenance and bounded identifier validation."""
    text = CHANGELOG_PATH.read_text(encoding="utf-8")
    old = (
        "- Bound OpenCode coverage source artifacts to one workflow attempt and immutable "
        "artifact ID, retained one-day source evidence, and made failed-jobs-only reruns "
        "fail closed with full-rerun or fresh-dispatch guidance instead of searching for "
        "expired or prior-attempt artifacts.\n"
    )
    new = (
        "- Bound OpenCode coverage source evidence to a validated immutable artifact ID and "
        "producer-attested workflow attempt, retained one-day source evidence, and made "
        "selective reruns fail closed before download on missing, malformed, or prior-attempt "
        "identity with full-rerun or fresh-dispatch guidance.\n"
    )
    if text.count(old) != 1:
        raise SystemExit("CHANGELOG artifact identity entry changed.")
    CHANGELOG_PATH.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    """Apply the permanent workflow, doctoring, and changelog repair."""
    patch_workflow()
    patch_doctoring()
    patch_changelog()


if __name__ == "__main__":
    main()
