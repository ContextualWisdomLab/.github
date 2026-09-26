"""Contract tests for the reusable default-branch Scorecard workflow."""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path
from typing import TypeAlias


ContractScalar: TypeAlias = str | list[str] | None
ContractMapping: TypeAlias = dict[tuple[str, ...], ContractScalar]
BLOCK_SCALAR_MARKERS = frozenset({"|", "|-", ">", ">-"})

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "scorecard-analysis.yml"


def _strip_inline_comment(line_text: str) -> str:
    """Remove an unquoted YAML comment without truncating quoted hash characters."""
    single_quoted = False
    double_quoted = False
    escape_next = False

    for character_index, current_character in enumerate(line_text):
        if escape_next:
            escape_next = False
            continue
        if current_character == "\\" and double_quoted:
            escape_next = True
            continue
        if current_character == "'" and not double_quoted:
            single_quoted = not single_quoted
            continue
        if current_character == '"' and not single_quoted:
            double_quoted = not double_quoted
            continue
        if (
            current_character == "#"
            and not single_quoted
            and not double_quoted
            and (
                character_index == 0
                or line_text[character_index - 1].isspace()
            )
        ):
            return line_text[:character_index].rstrip()

    if single_quoted or double_quoted:
        raise AssertionError(f"unterminated YAML quote: {line_text!r}")
    return line_text.rstrip()


def _split_mapping_entry(entry_text: str) -> tuple[str, str]:
    """Split one supported YAML mapping entry outside quotes and containers."""
    single_quoted = False
    double_quoted = False
    escape_next = False
    brace_depth = 0
    bracket_depth = 0

    for character_index, current_character in enumerate(entry_text):
        if escape_next:
            escape_next = False
            continue
        if current_character == "\\" and double_quoted:
            escape_next = True
            continue
        if current_character == "'" and not double_quoted:
            single_quoted = not single_quoted
            continue
        if current_character == '"' and not single_quoted:
            double_quoted = not double_quoted
            continue
        if single_quoted or double_quoted:
            continue
        if current_character == "{":
            brace_depth += 1
        elif current_character == "}":
            if brace_depth <= 0:
                raise AssertionError(f"unmatched YAML closing brace: {entry_text!r}")
            brace_depth -= 1
        elif current_character == "[":
            bracket_depth += 1
        elif current_character == "]":
            if bracket_depth <= 0:
                raise AssertionError(
                    f"unmatched YAML closing bracket: {entry_text!r}"
                )
            bracket_depth -= 1
        elif (
            current_character == ":"
            and brace_depth == 0
            and bracket_depth == 0
        ):
            mapping_key = entry_text[:character_index].strip()
            scalar_text = entry_text[character_index + 1 :].strip()
            if not mapping_key:
                raise AssertionError(f"empty YAML mapping key: {entry_text!r}")
            return mapping_key, scalar_text

    if single_quoted or double_quoted or brace_depth or bracket_depth:
        raise AssertionError(f"unterminated YAML mapping entry: {entry_text!r}")
    raise AssertionError(f"unsupported YAML mapping entry: {entry_text!r}")


def _parse_scalar_value(scalar_text: str) -> ContractScalar:
    """Parse only the scalar forms used by the governed workflow contract."""
    if not scalar_text:
        return None
    if scalar_text in BLOCK_SCALAR_MARKERS:
        return scalar_text
    if scalar_text[0] in {'"', "'", "["}:
        parsed_value = ast.literal_eval(scalar_text)
        if isinstance(parsed_value, list):
            assert all(
                isinstance(list_item, str) for list_item in parsed_value
            ), "workflow contract accepts only inline string lists"
            return parsed_value
        assert isinstance(parsed_value, str), (
            "workflow contract accepts only string scalar literals"
        )
        return parsed_value
    return scalar_text


def _parse_workflow_contract(yaml_text: str) -> ContractMapping:
    """Project supported YAML mappings into indentation-aware contract paths."""
    contract_mapping: ContractMapping = {}
    path_stack: list[tuple[int, str]] = []
    sequence_counts: dict[tuple[str, ...], int] = defaultdict(int)
    block_scalar_indent: int | None = None

    for raw_line in yaml_text.splitlines():
        if not raw_line.strip():
            continue

        leading_whitespace = raw_line[
            : len(raw_line) - len(raw_line.lstrip())
        ]
        if "\t" in leading_whitespace:
            raise AssertionError("tabs are not valid workflow indentation")
        indent_width = len(leading_whitespace)

        if block_scalar_indent is not None:
            if indent_width > block_scalar_indent:
                continue
            block_scalar_indent = None

        content_text = _strip_inline_comment(raw_line[indent_width:])
        if not content_text:
            continue

        while path_stack and path_stack[-1][0] >= indent_width:
            path_stack.pop()
        parent_path = tuple(
            path_component for _, path_component in path_stack
        )

        if content_text.startswith("- "):
            item_index = sequence_counts[parent_path]
            sequence_counts[parent_path] += 1
            item_component = f"[{item_index}]"
            path_stack.append((indent_width, item_component))
            item_text = content_text[2:].strip()
            if not item_text:
                contract_mapping[parent_path + (item_component,)] = None
                continue

            mapping_key, scalar_text = _split_mapping_entry(item_text)
            item_path = parent_path + (item_component, mapping_key)
            scalar_value = _parse_scalar_value(scalar_text)
            contract_mapping[item_path] = scalar_value
            if scalar_value is None:
                path_stack.append((indent_width + 1, mapping_key))
            elif (
                isinstance(scalar_value, str)
                and scalar_value in BLOCK_SCALAR_MARKERS
            ):
                block_scalar_indent = indent_width
            continue

        mapping_key, scalar_text = _split_mapping_entry(content_text)
        mapping_path = parent_path + (mapping_key,)
        scalar_value = _parse_scalar_value(scalar_text)
        contract_mapping[mapping_path] = scalar_value
        if scalar_value is None:
            path_stack.append((indent_width, mapping_key))
        elif (
            isinstance(scalar_value, str)
            and scalar_value in BLOCK_SCALAR_MARKERS
        ):
            block_scalar_indent = indent_width

    return contract_mapping


def _load_workflow_contract() -> ContractMapping:
    """Load the Scorecard workflow without undeclared test dependencies."""
    return _parse_workflow_contract(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _mapping_contract(
    workflow_contract: ContractMapping,
    mapping_prefix: tuple[str, ...],
) -> dict[str, ContractScalar]:
    """Return direct child values for one parsed mapping path."""
    return {
        mapping_path[-1]: scalar_value
        for mapping_path, scalar_value in workflow_contract.items()
        if len(mapping_path) == len(mapping_prefix) + 1
        and mapping_path[: len(mapping_prefix)] == mapping_prefix
    }


def _step_path_by_name(
    workflow_contract: ContractMapping,
    step_name: str,
) -> tuple[str, ...]:
    """Return the sequence-item path for one named analysis step."""
    steps_prefix = ("jobs", "analysis", "steps")
    for mapping_path, scalar_value in workflow_contract.items():
        if (
            len(mapping_path) == len(steps_prefix) + 2
            and mapping_path[: len(steps_prefix)] == steps_prefix
            and mapping_path[-1] == "name"
            and scalar_value == step_name
        ):
            return mapping_path[:-1]
    raise AssertionError(f"missing Scorecard workflow step: {step_name}")


def test_contract_parser_ignores_comments_and_block_scalar_decoys() -> None:
    """Comments and script literals must not satisfy workflow contracts."""
    fixture_text = """\
# workflow_call:
name: "Parser # fixture"
on:
  push:
    branches: ["develop"]
jobs:
  analysis:
    steps:
      - name: Script decoy
        run: |
          workflow_call:
          uses: attacker/example@mutable
          permissions:
            security-events: write
      - name: Checkout code
        uses: actions/checkout@immutable # pinned release annotation
        with:
          persist-credentials: false
"""
    fixture_contract = _parse_workflow_contract(fixture_text)

    assert fixture_contract[("name",)] == "Parser # fixture"
    assert fixture_contract[("on", "push", "branches")] == ["develop"]
    assert ("on", "workflow_call") not in fixture_contract
    assert (
        "jobs",
        "analysis",
        "steps",
        "[0]",
        "uses",
    ) not in fixture_contract
    checkout_path = _step_path_by_name(fixture_contract, "Checkout code")
    assert fixture_contract[checkout_path + ("uses",)] == (
        "actions/checkout@immutable"
    )
    assert fixture_contract[
        checkout_path + ("with", "persist-credentials")
    ] == "false"


def test_scorecard_analysis_is_reusable_without_losing_branch_history_triggers() -> None:
    """Preserve push and scheduled SARIF refresh while enabling reuse."""
    workflow_contract = _load_workflow_contract()

    assert workflow_contract[("on", "workflow_call")] is None
    assert workflow_contract[("on", "push", "branches")] == ["main"]
    assert workflow_contract[("on", "schedule", "[0]", "cron")] == (
        "30 1 * * 6"
    )


def test_scorecard_analysis_never_discards_an_in_flight_scans_evidence() -> None:
    """A newer queued push must never cancel an older scan mid-flight.

    .github#1768 (merged before this PR's own concurrency work landed) already
    added a ref-scoped, cancel-in-progress: false group to this file for
    exactly this reason: an in-flight Scorecard run's SARIF evidence for its
    own commit must never be discarded, only serialized behind. This PR's own
    earlier draft added a second, SHA-scoped, cancel-in-progress: true group to
    the same file -- a real, independently-reasoned fix for a different
    concern (the #1568-class stale-cancels-fresh race), but mutually exclusive
    with #1768's group as a single `concurrency:` block: SHA-scoping gives
    every distinct commit its own group, which would restore unbounded
    concurrent scans across a push burst -- the exact problem #1768 closed,
    and a direct regression of this org's standing Actions-queue-congestion
    priority. Kept #1768's group as authoritative.
    """
    workflow_contract = _load_workflow_contract()

    assert _mapping_contract(workflow_contract, ("concurrency",)) == {
        "group": "scorecard-analysis-${{ github.ref }}",
        "cancel-in-progress": "false",
    }


def test_scorecard_analysis_keeps_authoritative_sarif_boundaries() -> None:
    """Retain pinned analysis, credential hygiene, and SARIF upload."""
    workflow_contract = _load_workflow_contract()

    assert workflow_contract[("permissions",)] == "read-all"
    assert _mapping_contract(
        workflow_contract,
        ("jobs", "analysis", "permissions"),
    ) == {
        "security-events": "write",
        "id-token": "write",
        "contents": "read",
        "issues": "read",
        "pull-requests": "read",
        "checks": "read",
    }

    checkout_path = _step_path_by_name(workflow_contract, "Checkout code")
    assert workflow_contract[checkout_path + ("uses",)] == (
        "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
    )
    assert workflow_contract[
        checkout_path + ("with", "persist-credentials")
    ] == "false"

    analysis_path = _step_path_by_name(workflow_contract, "Run analysis")
    assert workflow_contract[analysis_path + ("uses",)] == (
        "ossf/scorecard-action@4eaacf0543bb3f2c246792bd56e8cdeffafb205a"
    )
    assert _mapping_contract(
        workflow_contract,
        analysis_path + ("with",),
    ) == {
        "results_file": "results.sarif",
        "results_format": "sarif",
        "publish_results": "false",
    }

    upload_path = _step_path_by_name(
        workflow_contract,
        "Upload to code scanning",
    )
    assert workflow_contract[upload_path + ("continue-on-error",)] == "true"
    assert workflow_contract[upload_path + ("uses",)] == (
        "github/codeql-action/upload-sarif@cdf488f595d80d6e07e03d4674febd5ab45fa938"
    )
    assert _mapping_contract(
        workflow_contract,
        upload_path + ("with",),
    ) == {"sarif_file": "results.sarif"}
