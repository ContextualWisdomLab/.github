#!/usr/bin/env python3
"""Apply the reviewed, one-shot PR 787 payload-binding repair."""

from __future__ import annotations

import textwrap
from pathlib import Path


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    """Replace one exact reviewed anchor or fail closed."""

    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one {label}, found {count}")
    return source.replace(old, new, 1)


def _indented_digest_block() -> str:
    """Return the wrapper-side canonical invocation-key verifier."""

    block = textwrap.dedent(
        """\
        python3 - <<'PY'
        import hashlib
        import hmac
        import json
        import os

        canonical = json.dumps(
            {
                "actor": os.environ["REQUESTED_BY"],
                "agent": os.environ["REQUESTED_AGENT"],
                "base_branch": os.environ["BASE_BRANCH"],
                "comment_id": int(os.environ["SOURCE_COMMENT_ID"]),
                "head_sha": os.environ["PR_HEAD_SHA"],
                "pr_number": int(os.environ["PR_NUMBER"]),
                "repository": os.environ["TARGET_REPOSITORY"],
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        calculated_key = hashlib.sha256(canonical).hexdigest()
        if not hmac.compare_digest(calculated_key, os.environ["INVOCATION_KEY"]):
            raise SystemExit("agent invocation key does not match canonical payload")
        PY

        """
    )
    return "".join(
        f"          {line}" if line.strip() else line
        for line in block.splitlines(keepends=True)
    )


def _repair_router() -> None:
    """Bind the Noema payload to the same base branch used by its digest."""

    path = Path("scripts/ci/agent_mention_router.py")
    source = path.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        '            "pr_head_sha": request.pull_request_head_sha,\n'
        '            "requested_agent": agent,\n',
        '            "pr_head_sha": request.pull_request_head_sha,\n'
        '            "base_branch": request.pull_request_base_branch,\n'
        '            "requested_agent": agent,\n',
        "Noema base-branch payload boundary",
    )
    path.write_text(source, encoding="utf-8")


def _repair_noema_wrapper() -> None:
    """Validate and forward the complete Noema invocation identity."""

    path = Path(".github/workflows/agent-mention-noema-dispatch.yml")
    source = path.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        "permissions:\n  actions: read\n  contents: write\n\njobs:\n  validate-and-forward:\n    if: github.repository == 'ContextualWisdomLab/.github'\n",
        "permissions:\n  actions: read\n  contents: read\n\njobs:\n  validate-and-forward:\n    if: github.repository == 'ContextualWisdomLab/.github'\n    permissions:\n      actions: read\n      contents: write\n",
        "Noema job-scoped write permission",
    )
    source = _replace_once(
        source,
        "      PR_HEAD_SHA: ${{ github.event.client_payload.pr_head_sha || '' }}\n"
        "      REQUESTED_BY: ${{ github.event.client_payload.requested_by || '' }}\n",
        "      PR_HEAD_SHA: ${{ github.event.client_payload.pr_head_sha || '' }}\n"
        "      BASE_BRANCH: ${{ github.event.client_payload.base_branch || '' }}\n"
        "      REQUESTED_BY: ${{ github.event.client_payload.requested_by || '' }}\n",
        "Noema base-branch environment binding",
    )
    source = _replace_once(
        source,
        '            ! [[ "$PR_HEAD_SHA" =~ ^[0-9a-f]{40}$ ]] ||\n'
        '            ! [[ "$SOURCE_COMMENT_ID" =~ ^[1-9][0-9]*$ ]] ||\n',
        '            ! [[ "$PR_HEAD_SHA" =~ ^[0-9a-f]{40}$ ]] ||\n'
        '            ! [[ "$BASE_BRANCH" =~ ^[A-Za-z0-9._/-]+$ ]] ||\n'
        '            [[ "$BASE_BRANCH" == -* ]] ||\n'
        '            ! [[ "$SOURCE_COMMENT_ID" =~ ^[1-9][0-9]*$ ]] ||\n',
        "Noema base-branch validation",
    )
    source = _replace_once(
        source,
        '          fi\n\n          marker="[cwl-agent-invocation:${INVOCATION_KEY}]"\n',
        '          fi\n\n'
        + _indented_digest_block()
        + '          marker="[cwl-agent-invocation:${INVOCATION_KEY}]"\n',
        "Noema digest verification insertion point",
    )
    source = _replace_once(
        source,
        '            --arg pr_head_sha "$PR_HEAD_SHA" \\\n'
        '            --arg requested_agent "$REQUESTED_AGENT" \\\n',
        '            --arg pr_head_sha "$PR_HEAD_SHA" \\\n'
        '            --arg base_branch "$BASE_BRANCH" \\\n'
        '            --arg requested_agent "$REQUESTED_AGENT" \\\n',
        "Noema forwarded base-branch argument",
    )
    source = _replace_once(
        source,
        "                pr_head_sha: $pr_head_sha,\n"
        "                requested_agent: $requested_agent,\n",
        "                pr_head_sha: $pr_head_sha,\n"
        "                base_branch: $base_branch,\n"
        "                requested_agent: $requested_agent,\n",
        "Noema forwarded base-branch field",
    )
    path.write_text(source, encoding="utf-8")


def _repair_opencode_wrapper() -> None:
    """Validate the complete OpenCode invocation identity before election."""

    path = Path(".github/workflows/agent-mention-opencode-dispatch.yml")
    source = path.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        "permissions:\n  actions: read\n  contents: write\n\njobs:\n  validate-and-forward:\n    if: github.repository == 'ContextualWisdomLab/.github'\n",
        "permissions:\n  actions: read\n  contents: read\n\njobs:\n  validate-and-forward:\n    if: github.repository == 'ContextualWisdomLab/.github'\n    permissions:\n      actions: read\n      contents: write\n",
        "OpenCode job-scoped write permission",
    )
    source = _replace_once(
        source,
        '          fi\n\n          marker="[cwl-agent-invocation:${INVOCATION_KEY}]"\n',
        '          fi\n\n'
        + _indented_digest_block()
        + '          marker="[cwl-agent-invocation:${INVOCATION_KEY}]"\n',
        "OpenCode digest verification insertion point",
    )
    path.write_text(source, encoding="utf-8")


def _repair_tests() -> None:
    """Extend invocation-key and payload identity regressions."""

    path = Path("tests/test_agent_mention_idempotency.py")
    source = path.read_text(encoding="utf-8")
    base_case = '''
        module.MentionRequest(
            original.repository,
            original.pull_request_number,
            original.pull_request_head_sha,
            "develop",
            original.comment_id,
            original.actor,
            original.agents,
        ),
'''
    source = _replace_once(
        source,
        '''        module.MentionRequest(
            original.repository,
            original.pull_request_number,
            "b" * 40,
            original.pull_request_base_branch,
            original.comment_id,
            original.actor,
            original.agents,
        ),
''',
        '''        module.MentionRequest(
            original.repository,
            original.pull_request_number,
            "b" * 40,
            original.pull_request_base_branch,
            original.comment_id,
            original.actor,
            original.agents,
        ),
'''
        + base_case,
        "base-branch-only invocation-key regression",
    )
    source = _replace_once(
        source,
        '        assert payload["pr_head_sha"] == mention_request.pull_request_head_sha\n'
        '        assert payload["source_comment_id"] == mention_request.comment_id\n',
        '        assert payload["pr_head_sha"] == mention_request.pull_request_head_sha\n'
        '        assert payload["base_branch"] == mention_request.pull_request_base_branch\n'
        '        assert payload["source_comment_id"] == mention_request.comment_id\n',
        "payload base-branch identity assertion",
    )
    path.write_text(source, encoding="utf-8")


def _repair_documentation() -> None:
    """Record the payload digest and least-privilege wrapper boundary."""

    path = Path("docs/automation/review-agent-comment-invocation.md")
    source = path.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        "Each requested agent receives a deterministic invocation key containing the target repository, PR number, exact head SHA, requested agent, and source comment ID. Agent-specific wrapper workflows use that key in their run title and non-cancelling concurrency group. The earliest central wrapper run is the durable leader; later exact-key runs suppress forwarding. Completed, failed, queued, and in-progress wrapper records therefore prevent duplicate forwarding, while a partially completed multi-agent request can retry only its missing agent.\n",
        "Each requested agent receives a deterministic invocation key containing the target repository, PR number, exact head SHA, base branch, requested agent, source comment ID, and requesting actor. Agent-specific wrapper workflows reconstruct the same sorted compact JSON identity and compare its SHA-256 digest before the key can participate in their run title, non-cancelling concurrency group, or durable-leader election. A syntactically valid key paired with altered payload fields therefore fails closed. The earliest valid central wrapper run is the durable leader; later exact-key runs suppress forwarding. Completed, failed, queued, and in-progress wrapper records prevent duplicate forwarding, while a partially completed multi-agent request can retry only its missing agent.\n",
        "operator digest-binding explanation",
    )
    source = _replace_once(
        source,
        "- The two agent-specific wrapper workflows receive only `actions: read` and `contents: write`.\n",
        "- The two agent-specific wrapper workflows keep workflow-default contents read-only; only their validated forwarding jobs receive `actions: read` and `contents: write`.\n",
        "wrapper permission explanation",
    )
    source = _replace_once(
        source,
        "The permanent quality workflow runs the deterministic router, sweep, durable-ledger, wrapper, receipt-authority, and workflow-contract suites under Python 3.14 and requires 100% production statement coverage, branch coverage, and public docstring coverage. It also compiles the Python files and checks the final diff for whitespace errors.\n",
        "The permanent quality workflow runs the deterministic router, sweep, durable-ledger, wrapper, payload-digest, receipt-authority, and workflow-contract suites under Python 3.14 and requires 100% production statement coverage, branch coverage, and public docstring coverage. It includes valid-format mismatched-key and base-branch-only identity regressions, compiles the Python files, and checks the final diff for whitespace errors.\n",
        "verification explanation",
    )
    path.write_text(source, encoding="utf-8")


def _repair_changelog() -> None:
    """Record the completed payload-bound invocation repair."""

    path = Path("CHANGELOG.md")
    source = path.read_text(encoding="utf-8")
    addition = (
        "- Bound each review-agent invocation key to the wrapper's complete canonical payload, including the base branch and requesting actor; altered fields with a valid-format key now fail before durable-leader election or forwarding, and wrapper write permission is job-scoped.\n"
    )
    if addition not in source:
        source = _replace_once(
            source,
            "### Fixed\n\n",
            "### Fixed\n\n" + addition,
            "Unreleased Fixed heading",
        )
    path.write_text(source, encoding="utf-8")


def main() -> int:
    """Apply every bounded repair component and return success."""

    _repair_router()
    _repair_noema_wrapper()
    _repair_opencode_wrapper()
    _repair_tests()
    _repair_documentation()
    _repair_changelog()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
