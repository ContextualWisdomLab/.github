#!/usr/bin/env python3
"""Materialize the reviewed OpenCode attempt-scoped artifact repair.

This helper is a temporary branch-local materializer. It changes only the central
OpenCode dispatch workflow and the Unreleased changelog entry. The permanent
behavior is guarded by ``tests/test_opencode_coverage_artifact_rerun_contract.py``.
"""

from __future__ import annotations

from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/opencode-review-dispatch.yml")
CHANGELOG_PATH = Path("CHANGELOG.md")


def action_expression(value: str) -> str:
    """Build a literal GitHub Actions expression at runtime."""
    return "$" + "{{ " + value + " }}"


def unique_index(
    lines: list[str],
    needle: str,
    *,
    start: int = 0,
    end: int | None = None,
    label: str,
) -> int:
    """Return the only exact line match inside a bounded range."""
    stop = len(lines) if end is None else end
    matches = [index for index in range(start, stop) if lines[index] == needle]
    if len(matches) != 1:
        raise SystemExit(
            f"Expected exactly one {label} line, found {len(matches)}."
        )
    return matches[0]


def patch_workflow() -> None:
    """Bind the coverage producer and consumer through an immutable artifact ID."""
    lines = WORKFLOW_PATH.read_text(encoding="utf-8").splitlines(keepends=True)

    producer_start = unique_index(
        lines,
        "  coverage-source-tree:\n",
        label="coverage-source-tree job",
    )
    consumer_start = unique_index(
        lines,
        "  coverage-evidence:\n",
        label="coverage-evidence job",
    )
    producer_env = unique_index(
        lines,
        "    env:\n",
        start=producer_start,
        end=consumer_start,
        label="coverage-source-tree env",
    )
    expected_permissions = [
        "    permissions:\n",
        "      contents: read\n",
        "      id-token: write\n",
    ]
    if lines[producer_env - 3 : producer_env] != expected_permissions:
        raise SystemExit(
            "coverage-source-tree permission boundary no longer matches the reviewed contract."
        )
    lines[producer_env:producer_env] = [
        "    outputs:\n",
        "      coverage_source_artifact_id: "
        + action_expression("steps.coverage_source_upload.outputs.artifact-id")
        + "\n",
    ]

    producer_start = unique_index(
        lines,
        "  coverage-source-tree:\n",
        label="coverage-source-tree job after output insertion",
    )
    consumer_start = unique_index(
        lines,
        "  coverage-evidence:\n",
        label="coverage-evidence job after output insertion",
    )
    upload_step = unique_index(
        lines,
        "      - name: Upload materialized pull request merge tree\n",
        start=producer_start,
        end=consumer_start,
        label="coverage source upload step",
    )
    if not lines[upload_step + 1].startswith("        uses: actions/upload-artifact@"):
        raise SystemExit("Coverage upload action anchor changed unexpectedly.")
    lines[upload_step + 1 : upload_step + 1] = ["        id: coverage_source_upload\n"]

    consumer_start = unique_index(
        lines,
        "  coverage-evidence:\n",
        label="coverage-evidence job after upload ID insertion",
    )
    upload_name = unique_index(
        lines,
        "          name: opencode-coverage-source\n",
        start=upload_step,
        end=consumer_start,
        label="coverage source upload name",
    )
    lines[upload_name] = (
        "          name: opencode-coverage-source-"
        + action_expression("github.run_attempt")
        + "\n"
    )

    consumer_start = unique_index(
        lines,
        "  coverage-evidence:\n",
        label="coverage-evidence job before download repair",
    )
    review_start = unique_index(
        lines,
        "  opencode-review-target:\n",
        start=consumer_start,
        label="opencode-review-target job",
    )
    download_step = unique_index(
        lines,
        "      - name: Download materialized pull request merge tree\n",
        start=consumer_start,
        end=review_start,
        label="coverage source download step",
    )
    if not lines[download_step + 1].startswith(
        "        uses: actions/download-artifact@"
    ):
        raise SystemExit("Coverage download action anchor changed unexpectedly.")
    lines[download_step] = (
        "      - name: Download current-attempt materialized pull request merge tree\n"
    )
    lines[download_step + 1 : download_step + 1] = [
        "        id: coverage_source_download\n",
        "        continue-on-error: true\n",
    ]

    review_start = unique_index(
        lines,
        "  opencode-review-target:\n",
        start=consumer_start,
        label="opencode-review-target job after download ID insertion",
    )
    download_name = unique_index(
        lines,
        "          name: opencode-coverage-source\n",
        start=download_step,
        end=review_start,
        label="coverage source download name",
    )
    lines[download_name] = (
        "          artifact-ids: "
        + action_expression(
            "needs.coverage-source-tree.outputs.coverage_source_artifact_id"
        )
        + "\n"
    )

    review_start = unique_index(
        lines,
        "  opencode-review-target:\n",
        start=consumer_start,
        label="opencode-review-target job before failure guidance insertion",
    )
    download_path = unique_index(
        lines,
        "          path: "
        + action_expression("runner.temp")
        + "/opencode-coverage-artifact\n",
        start=download_step,
        end=review_start,
        label="coverage source download path",
    )
    if lines[download_path + 1] != "\n":
        raise SystemExit("Expected a blank line after the coverage download step.")
    shell_run_attempt = "$" + "{GITHUB_RUN_ATTEMPT}"
    lines[download_path + 1 : download_path + 2] = [
        "\n",
        "      - name: Report missing current-attempt coverage source\n",
        "        if: steps.coverage_source_download.outcome != 'success'\n",
        "        env:\n",
        "          GITHUB_RUN_ATTEMPT: "
        + action_expression("github.run_attempt")
        + "\n",
        "        run: |\n",
        "          set -euo pipefail\n",
        "          echo \"::error::Coverage source evidence is unavailable for workflow run attempt "
        + shell_run_attempt
        + "; a failed-jobs-only rerun cannot safely reconstruct or reuse source evidence from another attempt.\"\n",
        "          echo \"::error::Use a full rerun or a fresh repository dispatch so coverage-source-tree uploads exact current-attempt evidence.\"\n",
        "          exit 1\n",
        "\n",
    ]

    WORKFLOW_PATH.write_text("".join(lines), encoding="utf-8")


def patch_changelog() -> None:
    """Record the attempt-scoped artifact correction under Unreleased fixes."""
    changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    marker = "### Fixed\n\n"
    entry = (
        "- Bound OpenCode coverage source artifacts to one workflow attempt and immutable "
        "artifact ID, retained one-day source evidence, and made failed-jobs-only reruns "
        "fail closed with full-rerun or fresh-dispatch guidance instead of searching for "
        "expired or prior-attempt artifacts.\n"
    )
    if changelog.count(marker) != 1:
        raise SystemExit("Expected exactly one Unreleased Fixed marker.")
    if entry not in changelog:
        changelog = changelog.replace(marker, marker + entry, 1)
    CHANGELOG_PATH.write_text(changelog, encoding="utf-8")


def main() -> None:
    """Apply the bounded workflow and changelog patch."""
    patch_workflow()
    patch_changelog()


if __name__ == "__main__":
    main()
