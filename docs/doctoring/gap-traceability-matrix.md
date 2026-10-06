# Gap traceability matrix

Status: proposed. Scope: ContextualWisdomLab/.github control plane.
Register: [`docs/product-technical-gap-baseline.md`](../product-technical-gap-baseline.md).
Tool: [`scripts/ci/gap_traceability_matrix.py`](../../scripts/ci/gap_traceability_matrix.py).

## Problem

The Gap baseline requires new work to link its Gap ID in the PR description
and test evidence. Nothing measured whether that happens. On 2026-10-06
12:30 KST, the authenticated `gh pr list` and `gh issue list` exports held 402
open PRs and 221 open issues. The tool found these results:

| Measure | Result |
| --- | --- |
| Register IDs (`G-`, `PRD-`, `CONTROL-` rows under a `Gap ID` or `ID` header) | 27, no duplicates |
| Open work items that mention a known register ID | 13 of 623 |
| Register IDs that no open work item mentions | 19 of 27 |
| IDs that open work cites but that the register does not define | 14 |

The 14 undefined IDs include `G-18` to `G-22`, `PRD-08`,
`CONTROL-PERSONAL-LITELLM-REVIEW-01` and seven other `CONTROL-*` incident IDs.
Some of them are defined only in an unmerged PR branch, and some appear in the
baseline only as prose instead of as a register row. For example,
`CONTROL-PERSONAL-LITELLM-REVIEW-01` is a row on the `align-pr-issue-runner`
branch (#2577), not on protected `main`. In both cases a reader of `main`
cannot resolve the reference.

These counts describe one snapshot. They do not authorize a merge and they
do not rank work.

## Decision

Add an offline, standard-library-only CLI that writes a JSON and Markdown
matrix from the register and the inventory exports:

```sh
gh pr list --state open --limit 1000 \
  --json number,title,body,isDraft,url > prs.json
gh issue list --state open --limit 1000 \
  --json number,title,body,url > issues.json
python3 scripts/ci/gap_traceability_matrix.py \
  --prs prs.json --issues issues.json \
  --output-json matrix.json --output-md matrix.md \
  --generated-at "$(date '+%Y-%m-%d %H:%M %Z')"
```

The report shows, for each register ID, the PRs and issues that mention it.
It also lists IDs without work, work without a known ID, dangling references
and duplicate register rows. The JSON records the SHA-256 digest of each input
so a reader can bind the report to its exact inputs.

`--require-link-event "$GITHUB_EVENT_PATH"` checks the PR in a live event
payload. `--require-link N` checks PR `N` in an exported inventory. Both exit 1
when the PR names no known register ID. This change does not add a workflow
or a required check. The current backlog would fail such a gate, so turning it
on needs a separate owner decision. That decision must say which PRs it
applies to, for example new non-bot PRs only.

## Matching rules

- A register row is a body row of a Markdown table whose header's first cell
  is `Gap ID` or `ID`, and whose first cell is exactly one ID. IDs in prose,
  in other cells and in other tables (such as the PR inventory) are mentions.
- Mentions are taken from the title and body. Fenced code, HTML comments,
  URLs and Markdown link targets are removed first. Inline code is removed
  unless its whole content is one ID, because PR bodies here usually quote IDs
  as code.
- An ID must not be attached to a letter, digit, `_`, `-`, `/` or a dotted
  name on its left, or to a letter, digit, `_` or `-` on its right. Korean
  particles such as `G-15를` still match.
- A range such as `G-17..G-22` yields only its two endpoints. Bodies use
  ranges both for "these gaps" and for "outside these gaps", so expanding
  them would create links that the author did not claim.

## Limits

- A mention is not evidence that the work implements, verifies or closes a
  gap. A body can list an ID without doing the work. Reviewers still judge
  substance.
- The tool reads one repository's inventory. Cross-repository work such as
  `naruon#974` is not linked.
- `gh` returns 30 items unless `--limit` is set. Check that the summary
  counts match the expected inventory size.
- Renamed or reused IDs, such as the earlier `G-15` collision, are reported
  only when two register rows exist at the same time.

## Method

The design used a mixture of agents from different model families. Codex
and OpenCode each proposed parsing rules, an exit-code contract and edge cases
independently. A Claude proposer ran twice and timed out both times without
an answer, so it contributed nothing. The implementation combines the points
both answers shared: the header-anchored register, removal of code and URLs,
exit codes 0/1/2/3 and checking the live event payload.

A separate read-only Codex pass then reviewed the implementation
adversarially. It timed out before writing a final answer, so its partial
reasoning trace was used. Each candidate finding was reproduced before it was
accepted:

- `G-04/G-09` lost the second ID. A slash now blocks a match only after a
  path segment, not after another ID.
- Example tables in fenced code were parsed as register rows. Fenced code,
  including indented, tilde and longer fences, is now skipped.
- An unclosed fence or HTML comment exposed the rest of the body. Both now
  run to the end of the text.
- A URL swallowed an ID attached to it after punctuation such as `)`.
- `--fail-on-duplicates` was ignored by the link-check modes, and an output
  write failure exited 1, the "unlinked" code. Both are fixed.
- `"isDraft": "false"` was read as a draft. Only JSON `true` counts now.

A timing probe found two quadratic regular expressions that hostile PR bodies
could trigger: an unclosed `<!--` repeated many times, and a long run of
hyphenated letters treated as a URL scheme. 100,000 repetitions of `G-01-`
took 13.8 seconds. After the fixes, every probed input of 40,000 to 400,000
repetitions finishes in about one second or less, and the time grows about
linearly. Regression tests bound these cases.

## Verification

- The focused suite passes: 55 tests in
  `tests/test_gap_traceability_matrix.py`, under both normal and
  `GITHUB_ACTIONS=true` runs.
- The new module has 100% statement and branch coverage, and `interrogate`
  reports 100% docstring coverage for it.
- One test parses the repository's own baseline and requires its register
  IDs to be unique.
- `interrogate scripts/ci` reports 97.0% on the clean protected-main tree
  `37b10243c`. This change does not lower that figure. The gap belongs to
  other modules.
