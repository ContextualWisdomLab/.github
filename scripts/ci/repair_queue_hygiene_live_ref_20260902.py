#!/usr/bin/env python3
"""Apply the current-main queue-hygiene live-ref repair exactly once."""

from pathlib import Path


SCHEDULER = Path(".github/workflows/pr-review-merge-scheduler.yml")
TEST = Path("tests/test_queue_hygiene_live_ref_current_head.py")
DOCTORING = Path("docs/doctoring/queue-hygiene-live-ref-race.md")
CHANGELOG = Path("CHANGELOG.md")
BASELINE = Path("docs/product-technical-gap-baseline.md")


def update_scheduler() -> None:
    source = SCHEDULER.read_text(encoding="utf-8")
    prefix = "      ORG_SWEEP_MAX_PRS:"
    lines = source.splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines) if line.startswith(prefix)]
    if len(matches) != 1 or "ORG_QUEUE_HYGIENE_MAX_REF_LOOKUPS:" in source:
        raise SystemExit("scheduler env anchor changed or repair already applied")
    expression = "$" + "{{ vars.ORG_QUEUE_HYGIENE_MAX_REF_LOOKUPS || '100' }}"
    lines.insert(
        matches[0] + 1,
        "      # Resolve each discovered PR branch through its live Git ref before any\n"
        "      # destructive queue-hygiene cancellation. Bound the lookup work\n"
        "      # independently so incomplete evidence can never authorize cancellation.\n"
        f"      ORG_QUEUE_HYGIENE_MAX_REF_LOOKUPS: {expression}\n",
    )
    source = "".join(lines)

    validation_anchor = '''          if ! [[ "$ORG_SWEEP_BRANCH_UPDATE_LIMIT" =~ ^(-1|[0-9]+)$ ]]; then
            echo "::error::ORG_SWEEP_BRANCH_UPDATE_LIMIT must be -1 or a non-negative integer; got '${ORG_SWEEP_BRANCH_UPDATE_LIMIT}'. Fix the ORG_SWEEP_BRANCH_UPDATE_LIMIT repository variable."
            exit 1
          fi
'''
    validation_insert = validation_anchor + '''          if ! [[ "$ORG_QUEUE_HYGIENE_MAX_REF_LOOKUPS" =~ ^[1-9][0-9]*$ ]]; then
            echo "::error::ORG_QUEUE_HYGIENE_MAX_REF_LOOKUPS must be a positive integer; got '${ORG_QUEUE_HYGIENE_MAX_REF_LOOKUPS}'. Fix the ORG_QUEUE_HYGIENE_MAX_REF_LOOKUPS repository variable."
            exit 1
          fi
'''
    if source.count(validation_anchor) != 1:
        raise SystemExit("scheduler validation anchor changed")
    source = source.replace(validation_anchor, validation_insert, 1)

    section_start = source.index("            # Queue hygiene, part 1:")
    old_start = source.index("            queue_hygiene_ready=true\n", section_start)
    old_end = source.index('            if ! current_default_sha="$(\n', old_start)
    old = source[old_start:old_end]
    if "value: .head.sha" not in old or ".head.sha != null" not in old:
        raise SystemExit("payload-head queue-hygiene contract changed")
    new = '''            queue_hygiene_ready=true
            open_pr_heads_json="{}"
            if open_pr_refs_tsv="$(
              gh api \\
                -H "Accept: application/vnd.github+json" \\
                "/repos/${repo_full_name}/pulls?state=open&per_page=100" \\
                --paginate \\
                | jq -sr '
                    add[]
                    | [
                        (if (.head.repo.full_name | type) == "string" then .head.repo.full_name else "" end),
                        (if (.head.ref | type) == "string" then .head.ref else "" end)
                      ]
                    | @tsv
                  '
            )"; then
              open_pr_refs_tsv="$(printf '%s\\n' "$open_pr_refs_tsv" | sort -u)"
              open_pr_ref_count="$(printf '%s\\n' "$open_pr_refs_tsv" | awk 'NF { count += 1 } END { print count + 0 }')"
              if (( open_pr_ref_count > ORG_QUEUE_HYGIENE_MAX_REF_LOOKUPS )); then
                echo "::warning::Current-HEAD cancellation skipped for ${repo_full_name}: ${open_pr_ref_count} open PR refs exceed the live-ref lookup limit ${ORG_QUEUE_HYGIENE_MAX_REF_LOOKUPS}. No run will be cancelled from incomplete evidence."
                queue_hygiene_ready=false
              elif [ -n "$open_pr_refs_tsv" ]; then
                while IFS=$'\\t' read -r head_repo head_ref; do
                  if [ -z "$head_repo" ] || [ -z "$head_ref" ]; then
                    echo "::warning::Current-HEAD cancellation skipped for ${repo_full_name}: an open PR has a malformed head repository or ref. No run will be cancelled from incomplete evidence."
                    queue_hygiene_ready=false
                    break
                  fi
                  encoded_head_ref="$(jq -rn --arg value "$head_ref" '$value | split("/") | map(@uri) | join("/")')"
                  if ! live_head_sha="$(
                    gh api \\
                      -H "Accept: application/vnd.github+json" \\
                      "/repos/${head_repo}/git/ref/heads/${encoded_head_ref}" \\
                      --jq '.object.sha // empty'
                  )" || ! [[ "$live_head_sha" =~ ^[0-9a-fA-F]{40}$ ]]; then
                    echo "::warning::Current-HEAD cancellation skipped for ${repo_full_name}: live ref ${head_repo}:${head_ref} could not be resolved safely. No run will be cancelled from incomplete evidence."
                    queue_hygiene_ready=false
                    break
                  fi
                  open_pr_heads_json="$(
                    jq \\
                      --arg key "${head_repo}:${head_ref}" \\
                      --arg value "$live_head_sha" \\
                      '. + {($key): $value}' \\
                      <<<"$open_pr_heads_json"
                  )"
                done <<<"$open_pr_refs_tsv"
              fi
            else
              echo "::warning::Current-HEAD cancellation skipped for ${repo_full_name}: open PR head refs could not be read safely. No run will be cancelled from incomplete evidence."
              queue_hygiene_ready=false
            fi
'''
    source = source[:old_start] + new + source[old_end:]
    SCHEDULER.write_text(source, encoding="utf-8")


def write_regression() -> None:
    TEST.write_text('''"""Regression contract for live-ref queue-hygiene cancellation."""\n\nfrom pathlib import Path\n\n\ndef _workflow() -> str:\n    return Path(".github/workflows/pr-review-merge-scheduler.yml").read_text(encoding="utf-8")\n\n\ndef _queue_hygiene_block() -> str:\n    workflow = _workflow()\n    start = workflow.index("# Queue hygiene, part 1:")\n    end = workflow.index("if ! current_default_sha=", start)\n    return workflow[start:end]\n\n\ndef test_queue_hygiene_resolves_live_git_refs_before_cancellation() -> None:\n    workflow = _workflow()\n    block = _queue_hygiene_block()\n    assert "ORG_QUEUE_HYGIENE_MAX_REF_LOOKUPS" in workflow\n    assert '"/repos/${head_repo}/git/ref/heads/${encoded_head_ref}"' in block\n    assert '$value | split("/") | map(@uri) | join("/")' in block\n    assert "--jq '.object.sha // empty'" in block\n    assert "value: .head.sha" not in block\n    assert ".head.sha != null" not in block\n\n\ndef test_queue_hygiene_fails_closed_on_partial_live_ref_evidence() -> None:\n    block = _queue_hygiene_block()\n    assert "open PR refs exceed the live-ref lookup limit" in block\n    assert "an open PR has a malformed head repository or ref" in block\n    assert "live ref ${head_repo}:${head_ref} could not be resolved safely" in block\n    assert block.count("queue_hygiene_ready=false") >= 3\n''', encoding="utf-8")


def write_docs() -> None:
    DOCTORING.write_text('''# Queue hygiene live-reference race\n\n## Incident\n\nThe organization queue sweep could observe a newly pushed PR head in Actions while the open-pull-request listing still exposed the predecessor SHA. Treating that payload SHA as authoritative let the sweep cancel legitimate current-head runs as superseded, creating a stale-event/concurrency admission cycle.\n\n## Decision\n\nOpen PR payloads are discovery-only for head repository and branch name. Before cancelling any PR run, the scheduler resolves every discovered branch through GitHub's live Git-reference endpoint and compares active runs with that authoritative SHA. A malformed/inaccessible ref or a lookup set above the bounded ceiling disables destructive cancellation for that repository; incomplete evidence can never authorize cancellation.\n\n## Verification\n\n`tests/test_queue_hygiene_live_ref_current_head.py` locks the live-ref endpoint, ref encoding, rejection of payload `.head.sha` as cancellation authority, lookup bound, and fail-closed error paths. Exact-head hosted checks remain authoritative after this source mutation.\n\n## Lineage\n\nThis is the current-main successor of historical PR #1348, ported onto protected main after #1630 reduced scheduler queue pressure. The historical branch was more than one hundred commits behind and conflicted with the current scheduler, so its semantic delta was reapplied without rewriting concurrent history.\n''', encoding="utf-8")

    text = CHANGELOG.read_text(encoding="utf-8")
    entry = '''- **Prevent stale PR payloads from cancelling current-head Actions runs.**\n  Organization queue hygiene now resolves every discovered PR branch through its\n  live Git ref before destructive cancellation and fails closed on missing,\n  malformed, or over-budget ref evidence. This ports the #1348 race repair onto\n  the post-#1630 scheduler without carrying its stale branch ancestry.\n'''
    marker = "## [Unreleased]\n"
    if text.count(marker) != 1:
        raise SystemExit("CHANGELOG Unreleased marker changed")
    if entry not in text:
        text = text.replace(marker, marker + entry, 1)
    CHANGELOG.write_text(text, encoding="utf-8")

    text = BASELINE.read_text(encoding="utf-8")
    section = '''\n## 2026-09-02 queue-hygiene live-ref stale-event repair\n\n- **Root cause:** organization queue hygiene treated the SHA cached in an open-PR listing as authoritative even though Actions can already contain runs for a newer branch head during GitHub propagation.\n- **Causal owner:** `ContextualWisdomLab/.github` scheduler control plane; historical owner PR #1348 was stale/conflicted after the #1630 queue-pressure merge.\n- **Repair:** discover repository/ref from the PR list, resolve each exact branch head through the Git refs API, bound lookups, and fail closed for that repository on any incomplete live-ref evidence before cancellation.\n- **Regression:** `tests/test_queue_hygiene_live_ref_current_head.py` proves payload `.head.sha` is not cancellation authority and locks malformed-ref, lookup-limit, live-ref lookup, and fail-closed behavior.\n- **Downstream expectation:** newly surfaced exact-head runs must no longer be retired because a predecessor SHA remains transiently visible in the PR-list payload; existing superseded runs remain cancellable once the live ref proves them stale.\n'''
    if "## 2026-09-02 queue-hygiene live-ref stale-event repair" not in text:
        text = text.rstrip() + "\n" + section
    BASELINE.write_text(text, encoding="utf-8")


def main() -> None:
    update_scheduler()
    write_regression()
    write_docs()


if __name__ == "__main__":
    main()
