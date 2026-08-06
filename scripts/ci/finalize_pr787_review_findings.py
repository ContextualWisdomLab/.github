#!/usr/bin/env python3
"""Apply the final deterministic review-finding repairs for PR 787."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    """Read one repository file as UTF-8 text."""

    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    """Write one repository file as normalized UTF-8 text."""

    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    """Replace exactly one literal block and fail on an unexpected source tree."""

    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement target, found {count}")
    write(path, content.replace(old, new, 1))


def replace_between(path: str, start: str, end: str, replacement: str) -> None:
    """Replace one section delimited by stable function markers."""

    content = read(path)
    start_index = content.index(start)
    end_index = content.index(end, start_index)
    write(path, content[:start_index] + replacement.rstrip() + "\n\n" + content[end_index + 1 :])


def update_router() -> None:
    """Harden validation, diagnostics, durable-run lookup, and rejection idempotency."""

    path = "scripts/ci/agent_mention_router.py"
    replace_once(
        path,
        "import subprocess\nfrom dataclasses import dataclass\nfrom typing import Any, Sequence\n",
        "import subprocess\nfrom dataclasses import dataclass\nfrom datetime import datetime, timedelta, timezone\nfrom typing import Any, Sequence\n",
    )
    replace_once(
        path,
        'BASE_BRANCH_RE = re.compile(r"^(?!-)[A-Za-z0-9._/-]+$")\nRECEIPT_RE = re.compile(r"<!-- cwl-agent-mention-receipt:(\\d+) -->")\nMAX_WORKFLOW_RUN_RECORDS = 10_000\n',
        'BASE_BRANCH_RE = re.compile(r"^(?!-)[A-Za-z0-9._/-]+$")\nACTOR_RE = re.compile(r"^[A-Za-z0-9-]+$")\nRECEIPT_RE = re.compile(r"<!-- cwl-agent-mention-receipt:(\\d+) -->")\nINVOCATION_MARKER_RE = re.compile(r"\\[cwl-agent-invocation:[0-9a-f]{64}\\]")\nMAX_WORKFLOW_RUN_RECORDS = 10_000\nWORKFLOW_RUN_LOOKBACK_HOURS = 24 * 30\n',
    )
    replace_once(
        path,
        dedent(
            '''
            completed = subprocess.run(
                command,
                input=None if input_payload is None else json.dumps(input_payload),
                text=True,
                capture_output=True,
                check=True,
                env=environment,
            )
            output = completed.stdout.strip()
            return None if not output else json.loads(output)
            '''
        ).strip(),
        dedent(
            '''
            completed = subprocess.run(
                command,
                input=None if input_payload is None else json.dumps(input_payload),
                text=True,
                capture_output=True,
                check=False,
                env=environment,
            )
            return_code = int(getattr(completed, "returncode", 0))
            if return_code:
                diagnostic = " ".join(
                    str(getattr(completed, "stderr", "") or "").split()
                )
                if not diagnostic:
                    diagnostic = "no stderr output"
                raise RuntimeError(
                    f"gh api failed with exit code {return_code}: {diagnostic[:2000]}"
                )
            output = completed.stdout.strip()
            return None if not output else json.loads(output)
            '''
        ).strip(),
    )
    replace_once(
        path,
        '    if not actor:\n        raise ValueError("comment actor is missing")\n',
        '    if not ACTOR_RE.fullmatch(actor):\n        raise ValueError("comment actor is missing or invalid")\n',
    )
    replace_once(
        path,
        "        if request.repository in opencode_allowlist:\n",
        "        normalized_allowlist = {entry.casefold() for entry in opencode_allowlist}\n        if request.repository.casefold() in normalized_allowlist:\n",
    )
    replace_once(
        path,
        "def _workflow_run_records(value: Any) -> tuple[dict[str, Any], ...]:\n",
        dedent(
            '''
            def workflow_run_cutoff(
                *,
                now: datetime | None = None,
                lookback_hours: int = WORKFLOW_RUN_LOOKBACK_HOURS,
            ) -> str:
                """Return the UTC lower bound for durable wrapper-run lookup."""

                current = now or datetime.now(timezone.utc)
                if current.tzinfo is None:
                    raise ValueError("workflow-run cutoff time must be timezone-aware")
                cutoff = current.astimezone(timezone.utc) - timedelta(hours=lookback_hours)
                return cutoff.replace(microsecond=0).isoformat().replace("+00:00", "Z")


            def _workflow_run_records(value: Any) -> tuple[dict[str, Any], ...]:
            '''
        ).strip() + "\n",
    )
    replace_between(
        path,
        "def dispatched_agents(\n",
        "\ndef noema_payload(\n",
        dedent(
            '''
            def dispatched_agents(
                request: MentionRequest,
                dispatch_client: GitHubClient,
                agents: Sequence[str] | None = None,
                *,
                workflow_run_since: str | None = None,
                run_marker_cache: dict[str, set[str]] | None = None,
            ) -> frozenset[str]:
                """Return agents with a durable central run for this exact invocation.

                Workflow inventories are bounded by the same maximum 30-day window as
                the scheduled source-comment sweep. A caller-owned marker cache avoids
                repeating the same agent workflow query for every candidate in one run.
                """

                candidates = tuple(request.agents if agents is None else agents)
                observed: set[str] = set()
                cutoff = workflow_run_since or workflow_run_cutoff()
                marker_cache = run_marker_cache if run_marker_cache is not None else {}
                for agent in candidates:
                    endpoint = AGENT_WORKFLOW_RUN_ENDPOINTS.get(agent)
                    if endpoint is None:
                        raise ValueError(f"unsupported agent: {agent}")
                    if endpoint not in marker_cache:
                        response = dispatch_client.request(
                            [
                                endpoint,
                                "-X",
                                "GET",
                                "-f",
                                "event=repository_dispatch",
                                "-f",
                                f"created=>={cutoff}",
                                "-f",
                                "per_page=100",
                                "--paginate",
                                "--slurp",
                            ]
                        )
                        markers: set[str] = set()
                        for run in _workflow_run_records(response):
                            run_id = run.get("id")
                            if (
                                isinstance(run_id, int)
                                and run_id > 0
                                and run.get("event") == "repository_dispatch"
                            ):
                                markers.update(
                                    INVOCATION_MARKER_RE.findall(
                                        str(run.get("display_title") or "")
                                    )
                                )
                        marker_cache[endpoint] = markers
                    if agent_invocation_marker(request, agent) in marker_cache[endpoint]:
                        observed.add(agent)
                return frozenset(observed)
            '''
        ).strip(),
    )
    replace_between(
        path,
        "def dispatch_request(\n",
        "\ndef load_event(\n",
        dedent(
            '''
            def dispatch_request(
                request: MentionRequest,
                *,
                target_client: GitHubClient,
                dispatch_client: GitHubClient,
                opencode_allowlist: frozenset[str],
                dry_run: bool = False,
                workflow_run_since: str | None = None,
                run_marker_cache: dict[str, set[str]] | None = None,
            ) -> tuple[str, ...]:
                """Dispatch missing agents and acknowledge only newly queued work."""

                dispatchable, rejected = eligible_agents(
                    request,
                    opencode_allowlist=opencode_allowlist,
                )
                if dry_run:
                    handles = tuple(f"@{agent}" for agent in dispatchable)
                    print(
                        "DRY-RUN agent mention "
                        f"repo={request.repository} pr={request.pull_request_number} "
                        f"head={request.pull_request_head_sha} "
                        f"dispatch={','.join(dispatchable) or 'none'} "
                        f"reject={','.join(rejected) or 'none'}"
                    )
                    return handles

                existing = dispatched_agents(
                    request,
                    dispatch_client,
                    dispatchable,
                    workflow_run_since=workflow_run_since,
                    run_marker_cache=run_marker_cache,
                )
                missing = tuple(agent for agent in dispatchable if agent not in existing)
                handles = tuple(f"@{agent}" for agent in missing)
                if not missing:
                    if rejected:
                        print(
                            "Rejected agent mention without target mutation "
                            f"repo={request.repository} pr={request.pull_request_number} "
                            f"comment={request.comment_id} "
                            f"agents={','.join(rejected)}"
                        )
                    return ()

                dispatch_endpoint = f"repos/{CENTRAL_AUTOMATION_REPOSITORY}/dispatches"
                if "cwl-noema-review" in missing:
                    dispatch_client.request(
                        [dispatch_endpoint, "-X", "POST"],
                        input_payload=noema_payload(request),
                    )
                    if run_marker_cache is not None:
                        endpoint = AGENT_WORKFLOW_RUN_ENDPOINTS["cwl-noema-review"]
                        run_marker_cache.setdefault(endpoint, set()).add(
                            agent_invocation_marker(request, "cwl-noema-review")
                        )
                if "opencode-agent" in missing:
                    dispatch_client.request(
                        [dispatch_endpoint, "-X", "POST"],
                        input_payload=opencode_payload(request),
                    )
                    if run_marker_cache is not None:
                        endpoint = AGENT_WORKFLOW_RUN_ENDPOINTS["opencode-agent"]
                        run_marker_cache.setdefault(endpoint, set()).add(
                            agent_invocation_marker(request, "opencode-agent")
                        )

                target_api = f"repos/{request.repository}"
                target_client.request(
                    [
                        f"{target_api}/issues/comments/{request.comment_id}/reactions",
                        "-X",
                        "POST",
                    ],
                    input_payload={"content": "eyes"},
                )
                status_parts: list[str] = []
                if handles:
                    status_parts.append(f"Queued {' and '.join(handles)}")
                existing_handles = tuple(
                    f"@{agent}" for agent in dispatchable if agent in existing
                )
                if existing_handles:
                    status_parts.append(
                        f"Already queued {' and '.join(existing_handles)} on this exact request"
                    )
                if rejected:
                    rejected_handles = " and ".join(f"@{agent}" for agent in rejected)
                    status_parts.append(
                        f"Rejected {rejected_handles}: repository is absent from "
                        "OPENCODE_REPOSITORY_DISPATCH_TARGETS"
                    )
                acknowledgement = (
                    f"{receipt_marker(request.comment_id)}\n"
                    f"{' ; '.join(status_parts)} for PR #{request.pull_request_number} at head "
                    f"`{request.pull_request_head_sha}`. Central exact-key workflow runs are "
                    "the durable dispatch ledger; existing review workflows remain "
                    "authoritative for the final verdict and failure evidence."
                )
                target_client.request(
                    [
                        f"{target_api}/issues/{request.pull_request_number}/comments",
                        "-X",
                        "POST",
                    ],
                    input_payload={"body": acknowledgement},
                )
                return handles
            '''
        ).strip(),
    )


def update_sweep() -> None:
    """Make repository traversal lazy and isolate per-repository/candidate failures."""

    path = "scripts/ci/agent_mention_sweep.py"
    replace_once(
        path,
        "import re\nfrom datetime import datetime, timedelta, timezone\nfrom typing import Any, Iterator, Sequence\n",
        "import re\nfrom dataclasses import dataclass\nfrom datetime import datetime, timedelta, timezone\nfrom typing import Any, Callable, Iterator, Sequence\n",
    )
    replace_once(
        path,
        'REPOSITORY_SOURCES = frozenset({"organization", "installation"})\n',
        dedent(
            '''
            REPOSITORY_SOURCES = frozenset({"organization", "installation"})


            @dataclass
            class SweepMetrics:
                """Mutable operational counters returned to the CLI boundary."""

                failures: int = 0
            '''
        ).strip() + "\n",
    )
    replace_once(
        path,
        dedent(
            '''
            pages = value if isinstance(value, list) else [value]
            records: list[dict[str, Any]] = []
            '''
        ).strip(),
        dedent(
            '''
            if (
                collection_key is None
                and isinstance(value, list)
                and all(isinstance(record, dict) for record in value)
            ):
                return list(value)
            pages = value if isinstance(value, list) else [value]
            records: list[dict[str, Any]] = []
            '''
        ).strip(),
    )
    replace_between(
        path,
        "def list_recent_pull_requests(\n",
        "\ndef list_recent_comments(\n",
        dedent(
            '''
            def list_recent_pull_requests(
                client: GitHubClient,
                *,
                organization: str,
                repository_source: str,
                since: str,
                on_error: Callable[[str, Exception], None] | None = None,
            ) -> Iterator[dict[str, Any]]:
                """Yield recent open pull requests with lazy cutoff-aware pagination."""

                cutoff = parse_timestamp(since)
                repositories = list_accessible_repositories(
                    client,
                    organization=organization,
                    repository_source=repository_source,
                )
                for repository in repositories:
                    try:
                        page = 1
                        while True:
                            response = client.request(
                                [
                                    f"repos/{repository}/pulls",
                                    "-X",
                                    "GET",
                                    "-f",
                                    "state=open",
                                    "-f",
                                    "sort=updated",
                                    "-f",
                                    "direction=desc",
                                    "-f",
                                    "per_page=100",
                                    "-f",
                                    f"page={page}",
                                ]
                            )
                            pull_requests = flatten_pages(response)
                            if not pull_requests:
                                break
                            reached_cutoff = False
                            for pull_request in pull_requests:
                                if (
                                    parse_timestamp(
                                        str(pull_request.get("updated_at") or "")
                                    )
                                    < cutoff
                                ):
                                    reached_cutoff = True
                                    break
                                number = pull_request.get("number")
                                if not isinstance(number, int) or number < 1:
                                    raise ValueError(
                                        "GitHub returned an invalid pull request number"
                                    )
                                yield {
                                    "number": number,
                                    "repository": repository,
                                    "pull_request": {
                                        "url": (
                                            "https://api.github.com/repos/"
                                            f"{repository}/pulls/{number}"
                                        )
                                    },
                                }
                            if reached_cutoff or len(pull_requests) < 100:
                                break
                            page += 1
                    except Exception as exc:
                        if on_error is None:
                            raise
                        on_error(repository, exc)
            '''
        ).strip(),
    )
    replace_between(
        path,
        "def sweep(\n",
        "\ndef main(\n",
        dedent(
            '''
            def sweep(
                *,
                target_client: GitHubClient,
                dispatch_client: GitHubClient,
                organization: str,
                repository_source: str,
                lookback_hours: int,
                max_dispatches: int,
                opencode_allowlist: frozenset[str],
                dry_run: bool = False,
                now: datetime | None = None,
                metrics: SweepMetrics | None = None,
            ) -> int:
                """Queue bounded new work while isolating candidate-local failures."""

                if max_dispatches < 1 or max_dispatches > 100:
                    raise ValueError("max dispatches must be between 1 and 100")
                since = cutoff_timestamp(lookback_hours, now=now)
                counters = metrics if metrics is not None else SweepMetrics()
                run_marker_cache: dict[str, set[str]] = {}
                dispatched = 0

                def record_failure(scope: str, error: Exception) -> None:
                    """Record one isolated error and preserve the remaining sweep."""

                    counters.failures += 1
                    message = " ".join(str(error).split()) or error.__class__.__name__
                    print(f"::warning::Agent mention sweep skipped {scope}: {message[:1000]}")

                for issue in list_recent_pull_requests(
                    target_client,
                    organization=organization,
                    repository_source=repository_source,
                    since=since,
                    on_error=record_failure,
                ):
                    issue_scope = f"{issue.get('repository')}#{issue.get('number')}"
                    try:
                        requests = build_requests_for_pull_request(
                            target_client,
                            issue=issue,
                            since=since,
                        )
                    except Exception as exc:
                        record_failure(issue_scope, exc)
                        continue
                    for request in requests:
                        request_scope = f"{issue_scope}/comment-{request.comment_id}"
                        try:
                            queued_agents = dispatch_request(
                                request,
                                target_client=target_client,
                                dispatch_client=dispatch_client,
                                opencode_allowlist=opencode_allowlist,
                                dry_run=dry_run,
                                workflow_run_since=since,
                                run_marker_cache=run_marker_cache,
                            )
                        except Exception as exc:
                            record_failure(request_scope, exc)
                            continue
                        if not queued_agents:
                            continue
                        dispatched += 1
                        if dispatched >= max_dispatches:
                            print(
                                "Agent mention sweep reached dispatch limit "
                                f"{max_dispatches}; isolated failures={counters.failures}."
                            )
                            return dispatched
                print(
                    "Agent mention sweep completed with "
                    f"{dispatched} dispatch(es) and {counters.failures} isolated failure(s)."
                )
                return dispatched
            '''
        ).strip(),
    )
    replace_once(
        path,
        dedent(
            '''
            sweep(
                target_client=GitHubClient(os.environ.get("TARGET_REPOSITORY_TOKEN", "")),
                dispatch_client=GitHubClient(os.environ.get("AGENT_DISPATCH_TOKEN", "")),
                organization=args.organization,
                repository_source=args.repository_source,
                lookback_hours=args.lookback_hours,
                max_dispatches=args.max_dispatches,
                opencode_allowlist=allowlist,
                dry_run=args.dry_run,
            )
            return 0
            '''
        ).strip(),
        dedent(
            '''
            metrics = SweepMetrics()
            sweep(
                target_client=GitHubClient(os.environ.get("TARGET_REPOSITORY_TOKEN", "")),
                dispatch_client=GitHubClient(os.environ.get("AGENT_DISPATCH_TOKEN", "")),
                organization=args.organization,
                repository_source=args.repository_source,
                lookback_hours=args.lookback_hours,
                max_dispatches=args.max_dispatches,
                opencode_allowlist=allowlist,
                dry_run=args.dry_run,
                metrics=metrics,
            )
            return 1 if metrics.failures else 0
            '''
        ).strip(),
    )


def wrapper_workflow(agent: str) -> str:
    """Return one complete resilient agent-wrapper workflow."""

    if agent == "noema":
        display = "Noema"
        requested_agent = "cwl-noema-review"
        workflow_file = "agent-mention-noema-dispatch.yml"
        source_event = "agent-mention-noema"
        target_event = "noema-review"
        extra_env = ""
        extra_validation = ""
        forwarded_controls = ""
        target_label = "authoritative Noema workflow"
    else:
        display = "OpenCode"
        requested_agent = "opencode-agent"
        workflow_file = "agent-mention-opencode-dispatch.yml"
        source_event = "agent-mention-opencode"
        target_event = "merge-scheduler"
        extra_env = dedent(
            '''
                  TRIGGER_REVIEWS: ${{ github.event.client_payload.trigger_reviews }}
                  REVIEW_DISPATCH_LIMIT: ${{ github.event.client_payload.review_dispatch_limit || '' }}
                  ENABLE_AUTO_MERGE: ${{ github.event.client_payload.enable_auto_merge }}
                  UPDATE_BRANCHES: ${{ github.event.client_payload.update_branches }}
                  MERGE_MODE: ${{ github.event.client_payload.merge_mode || '' }}
            '''
        )
        extra_validation = dedent(
            '''
                        [ "$TRIGGER_REVIEWS" != "true" ] ||
                        [ "$REVIEW_DISPATCH_LIMIT" != "1" ] ||
                        [ "$ENABLE_AUTO_MERGE" != "false" ] ||
                        [ "$UPDATE_BRANCHES" != "false" ] ||
                        [ "$MERGE_MODE" != "disabled" ] ||
            '''
        )
        forwarded_controls = dedent(
            '''
                            trigger_reviews: true,
                            review_dispatch_limit: "1",
                            enable_auto_merge: false,
                            update_branches: false,
                            merge_mode: "disabled",
            '''
        )
        target_label = "authoritative review-only scheduler"

    return dedent(
        f'''
        name: Agent Mention {display} Dispatch
        run-name: >-
          Agent Mention {display} ${{{{ github.event.client_payload.target_repository }}}}#${{{{
          github.event.client_payload.pr_number }}}} [cwl-agent-invocation:${{{{
          github.event.client_payload.agent_invocation_key }}}}]

        on:
          repository_dispatch:
            types: [{source_event}]

        concurrency:
          group: agent-mention-{agent}-${{{{ github.event.client_payload.agent_invocation_key || github.run_id }}}}
          cancel-in-progress: false
          queue: max

        permissions:
          contents: read

        jobs:
          validate-and-forward:
            if: github.repository == 'ContextualWisdomLab/.github'
            runs-on: ubuntu-24.04
            timeout-minutes: 5
            permissions:
              actions: read
              contents: write
            env:
              GH_TOKEN: ${{{{ github.token }}}}
              REQUESTED_AGENT: "{requested_agent}"
              PAYLOAD_AGENT: ${{{{ github.event.client_payload.requested_agent || '' }}}}
              INVOCATION_KEY: ${{{{ github.event.client_payload.agent_invocation_key || '' }}}}
              TARGET_REPOSITORY: ${{{{ github.event.client_payload.target_repository || '' }}}}
              PR_NUMBER: ${{{{ github.event.client_payload.pr_number || '' }}}}
              PR_HEAD_SHA: ${{{{ github.event.client_payload.pr_head_sha || '' }}}}
              BASE_BRANCH: ${{{{ github.event.client_payload.base_branch || '' }}}}
              REQUESTED_BY: ${{{{ github.event.client_payload.requested_by || '' }}}}
              SOURCE_COMMENT_ID: ${{{{ github.event.client_payload.source_comment_id || '' }}}}
        {extra_env.rstrip()}
            steps:
              - name: Validate exact invocation and elect one durable leader
                id: leader
                run: |
                  set -euo pipefail
                  if [ "$PAYLOAD_AGENT" != "$REQUESTED_AGENT" ] ||
                    ! [[ "$INVOCATION_KEY" =~ ^[0-9a-f]{{64}}$ ]] ||
                    ! [[ "$TARGET_REPOSITORY" =~ ^ContextualWisdomLab/[A-Za-z0-9_.-]+$ ]] ||
                    ! [[ "$PR_NUMBER" =~ ^[1-9][0-9]*$ ]] ||
                    ! [[ "$PR_HEAD_SHA" =~ ^[0-9a-f]{{40}}$ ]] ||
                    ! [[ "$BASE_BRANCH" =~ ^[A-Za-z0-9._/-]+$ ]] ||
                    [[ "$BASE_BRANCH" == -* ]] ||
                    ! [[ "$SOURCE_COMMENT_ID" =~ ^[1-9][0-9]*$ ]] ||
        {extra_validation.rstrip()}
                    ! [[ "$REQUESTED_BY" =~ ^[A-Za-z0-9-]+$ ]]; then
                    echo "::error::Rejected malformed or mismatched {display} agent invocation payload."
                    exit 1
                  fi

                  python3 - <<'PYTHON'
                  import hashlib
                  import hmac
                  import json
                  import os

                  canonical = json.dumps(
                      {{
                          "actor": os.environ["REQUESTED_BY"],
                          "agent": os.environ["REQUESTED_AGENT"],
                          "base_branch": os.environ["BASE_BRANCH"],
                          "comment_id": int(os.environ["SOURCE_COMMENT_ID"]),
                          "head_sha": os.environ["PR_HEAD_SHA"],
                          "pr_number": int(os.environ["PR_NUMBER"]),
                          "repository": os.environ["TARGET_REPOSITORY"],
                      }},
                      ensure_ascii=True,
                      separators=(",", ":"),
                      sort_keys=True,
                  ).encode("utf-8")
                  expected = hashlib.sha256(canonical).hexdigest()
                  if not hmac.compare_digest(expected, os.environ["INVOCATION_KEY"]):
                      raise SystemExit("invocation key does not match canonical payload")
                  PYTHON

                  marker="[cwl-agent-invocation:${{INVOCATION_KEY}}]"
                  matching_run_ids() {{
                    gh api --paginate --slurp \\
                      "repos/${{GITHUB_REPOSITORY}}/actions/workflows/{workflow_file}/runs?event=repository_dispatch&per_page=100" \\
                      | jq -r --arg marker "$marker" '
                          [.[].workflow_runs[]
                            | select((.display_title // "") | contains($marker))
                            | .id]
                          | unique
                          | sort
                          | .[]
                        '
                  }}

                  for attempt in 1 2 3; do
                    run_ids="$(matching_run_ids)"
                    lower_id="$(
                      awk -v current="$GITHUB_RUN_ID" '$1 < current {{ print $1; exit }}' \\
                        <<<"$run_ids"
                    )"
                    if [ -n "$lower_id" ]; then
                      echo "forward=false" >>"$GITHUB_OUTPUT"
                      echo "Duplicate exact-key invocation suppressed by lower durable run $lower_id."
                      exit 0
                    fi
                    if grep -Fxq "$GITHUB_RUN_ID" <<<"$run_ids"; then
                      echo "forward=true" >>"$GITHUB_OUTPUT"
                      exit 0
                    fi
                    if [ "$attempt" -lt 3 ]; then
                      sleep "$((attempt * 2))"
                    fi
                  done

                  echo "::notice::Current run remained absent from the eventually consistent workflow-run list after retries; self-electing because no lower durable run was observed."
                  echo "forward=true" >>"$GITHUB_OUTPUT"

              - name: Forward once to the {target_label}
                if: steps.leader.outputs.forward == 'true'
                run: |
                  set -euo pipefail
                  jq -n \\
                    --arg target_repository "$TARGET_REPOSITORY" \\
                    --argjson pr_number "$PR_NUMBER" \\
                    --arg pr_head_sha "$PR_HEAD_SHA" \\
                    --arg base_branch "$BASE_BRANCH" \\
                    --arg requested_agent "$REQUESTED_AGENT" \\
                    --arg agent_invocation_key "$INVOCATION_KEY" \\
                    --arg requested_by "$REQUESTED_BY" \\
                    --argjson source_comment_id "$SOURCE_COMMENT_ID" \\
                    '{{
                      event_type: "{target_event}",
                      client_payload: {{
                        target_repository: $target_repository,
                        pr_number: $pr_number,
                        pr_head_sha: $pr_head_sha,
                        base_branch: $base_branch,
        {forwarded_controls.rstrip()}
                        requested_agent: $requested_agent,
                        agent_invocation_key: $agent_invocation_key,
                        requested_by: $requested_by,
                        source_comment_id: $source_comment_id
                      }}
                    }}' \\
                    | gh api "repos/${{GITHUB_REPOSITORY}}/dispatches" -X POST --input -
        '''
    )


def update_workflows() -> None:
    """Harden wrapper election and keep exchanged credentials out of step outputs."""

    write(
        ".github/workflows/agent-mention-noema-dispatch.yml",
        wrapper_workflow("noema"),
    )
    write(
        ".github/workflows/agent-mention-opencode-dispatch.yml",
        wrapper_workflow("opencode"),
    )
    path = ".github/workflows/agent-mention-router.yml"
    content = read(path)
    content = content.replace(
        "curl -fsS \\\n              -H \"Authorization: Bearer ${ACTIONS_ID_TOKEN_REQUEST_TOKEN}\"",
        "curl -fsS --connect-timeout 10 --max-time 30 \\\n              -H \"Authorization: Bearer ${ACTIONS_ID_TOKEN_REQUEST_TOKEN}\"",
    )
    content = content.replace(
        "curl -fsS \\\n              -X POST \\\n              -H \"Authorization: Bearer ${oidc_token}\"",
        "curl -fsS --connect-timeout 10 --max-time 30 \\\n              -X POST \\\n              -H \"Authorization: Bearer ${oidc_token}\"",
    )
    old_output = dedent(
        '''
                  {
                    echo "available=true"
                    echo "token=$app_token"
                  } >>"$GITHUB_OUTPUT"
        '''
    ).strip()
    new_output = dedent(
        '''
                  echo "available=true" >>"$GITHUB_OUTPUT"
                  echo "SWEEP_APP_TOKEN=$app_token" >>"$GITHUB_ENV"
        '''
    ).strip()
    if old_output not in content:
        raise RuntimeError("agent-mention-router.yml: token output block changed")
    content = content.replace(old_output, new_output, 1)
    old_step = dedent(
        '''
              - name: Sweep recent organization PR comments
                env:
                  TARGET_REPOSITORY_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN || steps.sweep_app_token.outputs.token }}
                  TARGET_REPOSITORY_SOURCE: ${{ (secrets.PR_REVIEW_MERGE_TOKEN != '' || secrets.OPENCODE_APPROVE_TOKEN != '') && 'organization' || steps.sweep_app_token.outputs.available == 'true' && 'installation' || '' }}
                  AGENT_DISPATCH_TOKEN: ${{ github.token }}
                run: |
                  set -euo pipefail
                  if [ -z "${TARGET_REPOSITORY_TOKEN:-}" ] || [ -z "${TARGET_REPOSITORY_SOURCE:-}" ]; then
                    echo "::error::Agent mention sweep requires PR_REVIEW_MERGE_TOKEN, OPENCODE_APPROVE_TOKEN, or the OpenCode app token exchange."
                    exit 1
                  fi
                  args=(
                    --organization ContextualWisdomLab
                    --repository-source "$TARGET_REPOSITORY_SOURCE"
                    --lookback-hours "$LOOKBACK_HOURS"
                    --max-dispatches "$MAX_DISPATCHES"
                  )
                  if [ "$DRY_RUN" = "true" ]; then
                    args+=(--dry-run)
                  fi
                  python3 scripts/ci/agent_mention_sweep.py "${args[@]}"
        '''
    ).strip()
    new_step = dedent(
        '''
              - name: Sweep recent organization PR comments
                env:
                  PR_REVIEW_MERGE_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN }}
                  OPENCODE_APPROVE_TOKEN: ${{ secrets.OPENCODE_APPROVE_TOKEN }}
                  AGENT_DISPATCH_TOKEN: ${{ github.token }}
                run: |
                  set -euo pipefail
                  if [ -n "$PR_REVIEW_MERGE_TOKEN" ]; then
                    TARGET_REPOSITORY_TOKEN="$PR_REVIEW_MERGE_TOKEN"
                    TARGET_REPOSITORY_SOURCE="organization"
                  elif [ -n "$OPENCODE_APPROVE_TOKEN" ]; then
                    TARGET_REPOSITORY_TOKEN="$OPENCODE_APPROVE_TOKEN"
                    TARGET_REPOSITORY_SOURCE="organization"
                  else
                    TARGET_REPOSITORY_TOKEN="${SWEEP_APP_TOKEN:-}"
                    TARGET_REPOSITORY_SOURCE="${TARGET_REPOSITORY_TOKEN:+installation}"
                  fi
                  export TARGET_REPOSITORY_TOKEN
                  if [ -z "$TARGET_REPOSITORY_TOKEN" ] || [ -z "$TARGET_REPOSITORY_SOURCE" ]; then
                    echo "::error::Agent mention sweep requires PR_REVIEW_MERGE_TOKEN, OPENCODE_APPROVE_TOKEN, or the OpenCode app token exchange."
                    exit 1
                  fi
                  args=(
                    --organization ContextualWisdomLab
                    --repository-source "$TARGET_REPOSITORY_SOURCE"
                    --lookback-hours "$LOOKBACK_HOURS"
                    --max-dispatches "$MAX_DISPATCHES"
                  )
                  if [ "$DRY_RUN" = "true" ]; then
                    args+=(--dry-run)
                  fi
                  python3 scripts/ci/agent_mention_sweep.py "${args[@]}"
        '''
    ).strip()
    if old_step not in content:
        raise RuntimeError("agent-mention-router.yml: sweep step changed")
    write(path, content.replace(old_step, new_step, 1))

    quality_path = ".github/workflows/agent-mention-router-quality-ci.yml"
    quality = read(quality_path).replace(
        '      - "scripts/ci/agent_mention_invocation.py"\n', ""
    )
    write(quality_path, quality)


def update_tests() -> None:
    """Add executable regressions and repair full-suite-only brittle assertions."""

    router_test_path = "tests/test_agent_mention_router.py"
    old = dedent(
        '''
        def test_dispatch_rejects_unallowlisted_opencode_and_supports_dry_run(
            capsys,
        ) -> None:
            """OpenCode fails closed outside its allowlist while dry-run is mutation-free."""

            module = load_module()
            request = module.parse_event(event("@opencode-agent"))
            assert request is not None
            target = FakeClient()
            central = FakeClient()
            assert module.dispatch_request(
                request,
                target_client=target,
                dispatch_client=central,
                opencode_allowlist=frozenset(),
            ) == ()
            assert central.calls == []
            assert "Rejected @opencode-agent" in target.calls[-1][1]["body"]
            target = FakeClient()
            central = FakeClient()
            assert module.dispatch_request(
                request,
                target_client=target,
                dispatch_client=central,
                opencode_allowlist=frozenset(),
                dry_run=True,
            ) == ()
            assert target.calls == central.calls == []
            output = capsys.readouterr().out
            assert "DRY-RUN agent mention" in output
            assert "reject=opencode-agent" in output
        '''
    ).strip()
    new = dedent(
        '''
        def test_dispatch_rejects_unallowlisted_opencode_and_supports_dry_run(
            capsys,
        ) -> None:
            """Rejected-only and dry-run requests remain mutation-free."""

            module = load_module()
            request = module.parse_event(event("@opencode-agent"))
            assert request is not None
            target = FakeClient()
            central = FakeClient()
            assert module.dispatch_request(
                request,
                target_client=target,
                dispatch_client=central,
                opencode_allowlist=frozenset(),
            ) == ()
            assert target.calls == central.calls == []
            assert "Rejected agent mention without target mutation" in capsys.readouterr().out

            target = FakeClient()
            central = FakeClient()
            assert module.dispatch_request(
                request,
                target_client=target,
                dispatch_client=central,
                opencode_allowlist=frozenset(),
                dry_run=True,
            ) == ()
            assert target.calls == central.calls == []
            output = capsys.readouterr().out
            assert "DRY-RUN agent mention" in output
            assert "reject=opencode-agent" in output
        '''
    ).strip()
    replace_once(router_test_path, old, new)

    write(
        "tests/test_pr_review_fix_scheduler_coverage.py",
        dedent(
            '''
            """Coverage-only regressions for the review-fix scheduler."""

            import builtins
            import runpy

            import scripts.ci.pr_review_fix_scheduler as fix


            def test_import_falls_back_to_package_module(monkeypatch):
                """The scheduler remains importable when only the package path is available."""

                real_import = builtins.__import__

                def import_without_script_directory(
                    name,
                    globals_=None,
                    locals_=None,
                    fromlist=(),
                    level=0,
                ):
                    """Reject the script-directory import and delegate every other import."""

                    if name == "pr_review_merge_scheduler":
                        raise ModuleNotFoundError(name)
                    return real_import(name, globals_, locals_, fromlist, level)

                monkeypatch.setattr(
                    builtins,
                    "__import__",
                    import_without_script_directory,
                )
                namespace = runpy.run_path(
                    "scripts/ci/pr_review_fix_scheduler.py",
                    run_name="pr_review_fix_scheduler_package_fallback_test",
                )

                loaded = namespace["fetch_open_prs"]
                assert loaded.__name__ == fix.fetch_open_prs.__name__
                assert loaded.__code__.co_filename == fix.fetch_open_prs.__code__.co_filename


            def test_coverage_process_queue_skips_draft_and_wrong_base_and_external_repo(monkeypatch):
                """Draft, wrong-base, and external-head PRs are skipped."""

                def make_pr(number=1, **kwargs):
                    pr = {
                        "number": number,
                        "headRefOid": "abc",
                        "baseRefName": "main",
                        "headRefName": "feature",
                        "isDraft": False,
                        "headRepository": {"nameWithOwner": "owner/repo"},
                    }
                    pr.update(kwargs)
                    return pr

                args = fix.parse_args(["--repo", "owner/repo", "--base-branch", "main"])
                pr1 = make_pr(number=1, isDraft=True)
                pr2 = make_pr(number=2, baseRefName="other")
                pr3 = make_pr(number=3, headRepository={"nameWithOwner": "fork/repo"})
                monkeypatch.setattr(
                    fix,
                    "fetch_open_prs",
                    lambda repo, max_prs: [pr1, pr2, pr3],
                )
                monkeypatch.setattr(
                    fix,
                    "inspect_pr",
                    lambda repo, pr, args, **kwargs: ("skip", ("skip reason",)),
                )
                assert fix.process_queue(args) == 0


            def test_coverage_process_queue_exception_handling(monkeypatch):
                """One issue-comment lookup failure does not crash queue processing."""

                def make_pr(number=1, **kwargs):
                    pr = {
                        "number": number,
                        "headRefOid": "abc",
                        "baseRefName": "main",
                        "headRefName": "feature",
                        "isDraft": False,
                        "headRepository": {"nameWithOwner": "owner/repo"},
                    }
                    pr.update(kwargs)
                    return pr

                args = fix.parse_args(["--repo", "owner/repo", "--base-branch", "main"])
                pr1 = make_pr(number=1)
                pr2 = make_pr(number=2)
                monkeypatch.setattr(fix, "fetch_open_prs", lambda repo, max_prs: [pr1, pr2])
                monkeypatch.setattr(fix, "needs_autofix", lambda pr: (True, ("reason",)))

                def raise_error(repo, number):
                    raise RuntimeError("boom")

                monkeypatch.setattr(fix, "issue_comments", raise_error)
                monkeypatch.setattr(
                    fix,
                    "inspect_pr",
                    lambda repo, pr, args, **kwargs: ("skip", ("skip reason",)),
                )
                assert fix.process_queue(args) == 0
            '''
        ),
    )

    write(
        "tests/test_agent_mention_downstream_idempotency.py",
        dedent(
            '''
            """Static contracts for downstream review-agent invocation idempotency."""

            from pathlib import Path

            ROOT = Path(__file__).resolve().parents[1]
            ROUTER_WORKFLOW = ROOT / ".github" / "workflows" / "agent-mention-router.yml"
            QUALITY_WORKFLOW = ROOT / ".github" / "workflows" / "agent-mention-router-quality-ci.yml"
            NOEMA_WORKFLOW = ROOT / ".github" / "workflows" / "agent-mention-noema-dispatch.yml"
            OPENCODE_WORKFLOW = ROOT / ".github" / "workflows" / "agent-mention-opencode-dispatch.yml"
            ROUTER_SCRIPT = ROOT / "scripts" / "ci" / "agent_mention_router.py"


            def test_router_can_read_durable_central_workflow_runs() -> None:
                """Both local routing and sibling sweeping receive actions read access."""

                text = ROUTER_WORKFLOW.read_text(encoding="utf-8")
                local, sweep = text.split("\n  sweep-organization-agent-mentions:\n", 1)
                assert "permissions:\n      actions: read" in local
                assert "permissions:\n      actions: read" in sweep
                assert "AGENT_DISPATCH_TOKEN: ${{ github.token }}" in local
                assert "AGENT_DISPATCH_TOKEN: ${{ github.token }}" in sweep


            def test_downstream_workflows_retry_visibility_and_bind_exact_key() -> None:
                """Wrappers queue duplicates and never lose a request to eventual consistency."""

                noema = NOEMA_WORKFLOW.read_text(encoding="utf-8")
                opencode = OPENCODE_WORKFLOW.read_text(encoding="utf-8")
                for text in (noema, opencode):
                    assert "github.event.client_payload.agent_invocation_key" in text
                    assert "cwl-agent-invocation:" in text
                    assert "source_comment_id" in text
                    assert "requested_agent" in text
                    assert "cancel-in-progress: false" in text
                    assert "queue: max" in text
                    assert "for attempt in 1 2 3" in text
                    assert 'sleep "$((attempt * 2))"' in text
                    assert "no lower durable run was observed" in text
                    assert "^[0-9a-f]{64}$" in text
                    assert "^[1-9][0-9]*$" in text
                    assert "repos/${GITHUB_REPOSITORY}/dispatches" in text
                assert "types: [agent-mention-noema]" in noema
                assert 'event_type: "noema-review"' in noema
                assert 'REQUESTED_AGENT: "cwl-noema-review"' in noema
                assert "types: [agent-mention-opencode]" in opencode
                assert 'event_type: "merge-scheduler"' in opencode
                assert 'REQUESTED_AGENT: "opencode-agent"' in opencode
                assert '[[ "$BASE_BRANCH" =~ ^[A-Za-z0-9._/-]+$ ]]' in opencode
                assert '[[ "$BASE_BRANCH" == -* ]]' in opencode


            def test_wrappers_recompute_the_router_canonical_payload_digest() -> None:
                """A syntactically valid key cannot authorize altered payload fields."""

                router = ROUTER_SCRIPT.read_text(encoding="utf-8")
                noema_function = router.split("def noema_payload", 1)[1].split(
                    "def opencode_payload", 1
                )[0]
                assert '"base_branch": request.pull_request_base_branch' in noema_function

                canonical_fields = (
                    '"actor"',
                    '"agent"',
                    '"base_branch"',
                    '"comment_id"',
                    '"head_sha"',
                    '"pr_number"',
                    '"repository"',
                )
                for text in (
                    NOEMA_WORKFLOW.read_text(encoding="utf-8"),
                    OPENCODE_WORKFLOW.read_text(encoding="utf-8"),
                ):
                    assert "BASE_BRANCH:" in text
                    assert "import hashlib" in text
                    assert "import hmac" in text
                    assert "json.dumps(" in text
                    assert 'separators=(",", ":")' in text
                    assert "sort_keys=True" in text
                    assert "hashlib.sha256" in text
                    assert "hmac.compare_digest" in text
                    assert "INVOCATION_KEY" in text
                    for field in canonical_fields:
                        assert field in text


            def test_quality_gate_runs_full_suite_for_docs_and_exact_diff() -> None:
                """Every changed contract executes while coverage stays source-bounded."""

                text = QUALITY_WORKFLOW.read_text(encoding="utf-8")
                assert '      - "docs/automation/review-agent-comment-invocation.md"' in text
                assert '      - "tests/test_agent_mention_*.py"' in text
                assert "python -m coverage run -m pytest -q\n" in text
                assert "python -m compileall -q scripts/ci tests" in text
                assert "CHANGE_DIFF_RANGE" in text
                assert 'git diff --check "$CHANGE_DIFF_RANGE"' in text
                coverage_config = text.split("[run]\n", 1)[1].split("[report]\n", 1)[0]
                assert "scripts/ci/agent_mention_router.py" in coverage_config
                assert "scripts/ci/agent_mention_sweep.py" in coverage_config
            '''
        ),
    )

    write(
        "tests/test_agent_mention_review_regressions.py",
        dedent(
            '''
            """Review-driven runtime regressions for the agent mention control plane."""

            from __future__ import annotations

            import importlib.util
            import sys
            from datetime import datetime, timezone
            from pathlib import Path
            from types import ModuleType, SimpleNamespace

            import pytest

            ROOT = Path(__file__).resolve().parents[1]
            MODULE_PATH = ROOT / "scripts" / "ci" / "agent_mention_router.py"


            def load_module() -> ModuleType:
                """Load the router under one isolated module name."""

                module_name = "agent_mention_router_review_regressions"
                spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
                assert spec and spec.loader
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                return module


            def request(module: ModuleType, agents=("cwl-noema-review", "opencode-agent")):
                """Build one exact invocation request."""

                return module.MentionRequest(
                    "ContextualWisdomLab/Example",
                    17,
                    "a" * 40,
                    "main",
                    91,
                    "maintainer",
                    agents,
                )


            class FakeClient:
                """Capture API requests and expose endpoint-keyed run inventories."""

                def __init__(self, responses=None) -> None:
                    """Initialize responses and an empty call ledger."""

                    self.responses = responses or {}
                    self.calls: list[tuple[list[str], dict | None]] = []

                def request(self, args, *, input_payload=None):
                    """Record a call and return its registered response."""

                    self.calls.append((list(args), input_payload))
                    if args[0].endswith("/runs"):
                        return self.responses.get(args[0], {"workflow_runs": []})
                    return None


            def test_actor_and_allowlist_validation_are_wrapper_compatible() -> None:
                """Router validation rejects actors wrappers cannot accept."""

                module = load_module()
                payload = {
                    "repository": {"full_name": "ContextualWisdomLab/Example"},
                    "issue": {"number": 17, "pull_request": {"url": "x"}},
                    "comment": {
                        "id": 91,
                        "body": "@opencode-agent",
                        "author_association": "MEMBER",
                        "user": {"login": "bad_actor", "type": "User"},
                    },
                    "pull_request": {
                        "state": "open",
                        "head": {"sha": "a" * 40},
                        "base": {"ref": "main"},
                    },
                }
                with pytest.raises(ValueError, match="actor"):
                    module.parse_event(payload)

                mention = request(module, ("opencode-agent",))
                assert module.eligible_agents(
                    mention,
                    opencode_allowlist=frozenset({"contextualwisdomlab/example"}),
                ) == (("opencode-agent",), ())


            @pytest.mark.parametrize(
                ("stderr", "message"),
                [("permission denied\n details", "permission denied details"), ("", "no stderr")],
            )
            def test_github_client_surfaces_bounded_api_diagnostics(
                monkeypatch,
                stderr: str,
                message: str,
            ) -> None:
                """A failed gh call identifies the real API boundary."""

                module = load_module()
                monkeypatch.setattr(
                    module.subprocess,
                    "run",
                    lambda *args, **kwargs: SimpleNamespace(
                        stdout="",
                        stderr=stderr,
                        returncode=1,
                    ),
                )
                with pytest.raises(RuntimeError, match=message):
                    module.GitHubClient("token").request(["repos/x/y"])


            def test_workflow_run_cutoff_and_marker_cache_bound_api_cost() -> None:
                """Each agent workflow inventory is queried once per sweep window."""

                module = load_module()
                now = datetime(2026, 8, 6, 12, tzinfo=timezone.utc)
                cutoff = module.workflow_run_cutoff(now=now, lookback_hours=24)
                assert cutoff == "2026-08-05T12:00:00Z"
                with pytest.raises(ValueError, match="timezone-aware"):
                    module.workflow_run_cutoff(now=datetime(2026, 8, 6))

                mention = request(module)
                noema_endpoint = module.AGENT_WORKFLOW_RUN_ENDPOINTS["cwl-noema-review"]
                noema_marker = module.agent_invocation_marker(
                    mention, "cwl-noema-review"
                )
                client = FakeClient(
                    {
                        noema_endpoint: {
                            "workflow_runs": [
                                {
                                    "id": 1,
                                    "event": "repository_dispatch",
                                    "display_title": f"run {noema_marker}",
                                }
                            ]
                        }
                    }
                )
                cache: dict[str, set[str]] = {}
                expected = frozenset({"cwl-noema-review"})
                assert module.dispatched_agents(
                    mention,
                    client,
                    workflow_run_since=cutoff,
                    run_marker_cache=cache,
                ) == expected
                assert module.dispatched_agents(
                    mention,
                    client,
                    workflow_run_since=cutoff,
                    run_marker_cache=cache,
                ) == expected
                run_calls = [args for args, _ in client.calls if args[0].endswith("/runs")]
                assert len(run_calls) == 2
                assert all(f"created=>={cutoff}" in args for args in run_calls)


            def test_dispatch_cache_suppresses_same_run_retries_and_rejection_noise() -> None:
                """Accepted dispatches update the in-memory ledger before wrapper visibility."""

                module = load_module()
                mention = request(module)
                target = FakeClient()
                central = FakeClient()
                cache: dict[str, set[str]] = {}
                allowlist = frozenset({"contextualwisdomlab/example"})

                assert module.dispatch_request(
                    mention,
                    target_client=target,
                    dispatch_client=central,
                    opencode_allowlist=allowlist,
                    workflow_run_since="2026-08-01T00:00:00Z",
                    run_marker_cache=cache,
                ) == ("@cwl-noema-review", "@opencode-agent")
                first_target_calls = len(target.calls)
                assert module.dispatch_request(
                    mention,
                    target_client=target,
                    dispatch_client=central,
                    opencode_allowlist=allowlist,
                    workflow_run_since="2026-08-01T00:00:00Z",
                    run_marker_cache=cache,
                ) == ()
                assert len(target.calls) == first_target_calls
                dispatches = [
                    payload["event_type"]
                    for args, payload in central.calls
                    if args[0].endswith("/dispatches") and payload
                ]
                assert dispatches == ["agent-mention-noema", "agent-mention-opencode"]

                mixed = request(module)
                mixed_target = FakeClient()
                mixed_central = FakeClient()
                mixed_cache: dict[str, set[str]] = {}
                assert module.dispatch_request(
                    mixed,
                    target_client=mixed_target,
                    dispatch_client=mixed_central,
                    opencode_allowlist=frozenset(),
                    run_marker_cache=mixed_cache,
                ) == ("@cwl-noema-review",)
                first_mixed_calls = len(mixed_target.calls)
                assert module.dispatch_request(
                    mixed,
                    target_client=mixed_target,
                    dispatch_client=mixed_central,
                    opencode_allowlist=frozenset(),
                    run_marker_cache=mixed_cache,
                ) == ()
                assert len(mixed_target.calls) == first_mixed_calls
            '''
        ),
    )

    write(
        "tests/test_agent_mention_sweep_regressions.py",
        dedent(
            '''
            """Review-driven pagination and failure-isolation regressions."""

            from __future__ import annotations

            import importlib
            import sys
            from datetime import datetime, timezone
            from pathlib import Path

            import pytest

            ROOT = Path(__file__).resolve().parents[1]
            SCRIPTS = ROOT / "scripts" / "ci"
            sys.path.insert(0, str(SCRIPTS))


            def module():
                """Reload the sweep module for isolated monkeypatching."""

                return importlib.reload(importlib.import_module("agent_mention_sweep"))


            def repository(name: str) -> dict:
                """Build one active organization repository record."""

                return {
                    "full_name": f"ContextualWisdomLab/{name}",
                    "owner": {"login": "ContextualWisdomLab"},
                    "archived": False,
                    "disabled": False,
                }


            class PagingClient:
                """Serve page-aware endpoint responses and deterministic failures."""

                def __init__(self, responses) -> None:
                    """Initialize an endpoint/page response map."""

                    self.responses = responses
                    self.calls: list[list[str]] = []

                def request(self, args, *, input_payload=None):
                    """Return one endpoint/page response or raise its configured error."""

                    del input_payload
                    args = list(args)
                    self.calls.append(args)
                    endpoint = args[0]
                    page = 1
                    for index, value in enumerate(args[:-1]):
                        if value == "-f" and args[index + 1].startswith("page="):
                            page = int(args[index + 1].split("=", 1)[1])
                    response = self.responses[(endpoint, page)]
                    if isinstance(response, Exception):
                        raise response
                    return response


            def pull(number: int, updated_at: str = "2026-08-06T11:00:00Z") -> dict:
                """Build one pull-list response record."""

                return {"number": number, "updated_at": updated_at}


            def test_pull_pagination_stops_at_cutoff_without_loading_later_pages() -> None:
                """Updated-descending pages stop immediately at the first old record."""

                sweep = module()
                recent = [pull(number) for number in range(1, 101)]
                client = PagingClient(
                    {
                        ("orgs/ContextualWisdomLab/repos", 1): [[repository("example")]],
                        ("repos/ContextualWisdomLab/example/pulls", 1): recent,
                        ("repos/ContextualWisdomLab/example/pulls", 2): [
                            pull(101, "2026-08-01T00:00:00Z")
                        ],
                    }
                )
                results = list(
                    sweep.list_recent_pull_requests(
                        client,
                        organization="ContextualWisdomLab",
                        repository_source="organization",
                        since="2026-08-05T00:00:00Z",
                    )
                )
                assert len(results) == 100
                pull_calls = [
                    args for args in client.calls if args[0].endswith("/pulls")
                ]
                assert len(pull_calls) == 2
                assert not any("page=3" in args for args in pull_calls)
                assert sweep.flatten_pages([{"number": 1}]) == [{"number": 1}]


            def test_repository_failure_is_isolated_and_later_repository_runs() -> None:
                """A repository-local API failure does not terminate organization traversal."""

                sweep = module()
                client = PagingClient(
                    {
                        ("orgs/ContextualWisdomLab/repos", 1): [[
                            repository("broken"),
                            repository("healthy"),
                        ]],
                        ("repos/ContextualWisdomLab/broken/pulls", 1): RuntimeError(
                            "forbidden"
                        ),
                        ("repos/ContextualWisdomLab/healthy/pulls", 1): [pull(7)],
                    }
                )
                failures = []
                results = list(
                    sweep.list_recent_pull_requests(
                        client,
                        organization="ContextualWisdomLab",
                        repository_source="organization",
                        since="2026-08-05T00:00:00Z",
                        on_error=lambda scope, error: failures.append(
                            (scope, str(error))
                        ),
                    )
                )
                assert [result["repository"] for result in results] == [
                    "ContextualWisdomLab/healthy"
                ]
                assert failures == [("ContextualWisdomLab/broken", "forbidden")]


            def mention_request(comment_id: int):
                """Build one Noema request for orchestration isolation tests."""

                router = importlib.import_module("agent_mention_router")
                return router.MentionRequest(
                    "ContextualWisdomLab/example",
                    7,
                    "a" * 40,
                    "main",
                    comment_id,
                    "maintainer",
                    ("cwl-noema-review",),
                )


            def test_sweep_continues_after_candidate_and_dispatch_failures(
                monkeypatch,
                capsys,
            ) -> None:
                """Candidate-local failures are counted while later work is queued."""

                sweep = module()
                issues = [
                    {"repository": "ContextualWisdomLab/example", "number": 7},
                    {"repository": "ContextualWisdomLab/example", "number": 8},
                ]
                monkeypatch.setattr(
                    sweep,
                    "list_recent_pull_requests",
                    lambda *args, **kwargs: iter(issues),
                )

                def build_requests(client, *, issue, since):
                    del client, since
                    if issue["number"] == 7:
                        raise RuntimeError("comment inventory failed")
                    return (mention_request(10), mention_request(11))

                monkeypatch.setattr(sweep, "build_requests_for_pull_request", build_requests)
                dispatch_kwargs = []

                def dispatch(request, **kwargs):
                    dispatch_kwargs.append(kwargs)
                    if request.comment_id == 10:
                        raise RuntimeError("dispatch failed")
                    return ("@cwl-noema-review",)

                monkeypatch.setattr(sweep, "dispatch_request", dispatch)
                metrics = sweep.SweepMetrics()
                assert sweep.sweep(
                    target_client=object(),
                    dispatch_client=object(),
                    organization="ContextualWisdomLab",
                    repository_source="organization",
                    lookback_hours=24,
                    max_dispatches=5,
                    opencode_allowlist=frozenset(),
                    now=datetime(2026, 8, 6, tzinfo=timezone.utc),
                    metrics=metrics,
                ) == 1
                assert metrics.failures == 2
                assert dispatch_kwargs[0]["run_marker_cache"] is dispatch_kwargs[1][
                    "run_marker_cache"
                ]
                assert dispatch_kwargs[0]["workflow_run_since"].endswith("Z")
                output = capsys.readouterr().out
                assert "comment inventory failed" in output
                assert "dispatch failed" in output


            def test_main_returns_failure_when_isolated_errors_were_observed(
                monkeypatch,
            ) -> None:
                """The scheduled workflow remains visibly failed after partial progress."""

                sweep = module()
                monkeypatch.setenv("TARGET_REPOSITORY_TOKEN", "target")
                monkeypatch.setenv("AGENT_DISPATCH_TOKEN", "dispatch")

                def fail_partially(**kwargs):
                    kwargs["metrics"].failures = 1
                    return 0

                monkeypatch.setattr(sweep, "sweep", fail_partially)
                assert sweep.main([]) == 1
            '''
        ),
    )


def main() -> int:
    """Apply every deterministic final-state transformation."""

    update_router()
    update_sweep()
    update_workflows()
    update_tests()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
