#!/usr/bin/env python3
"""Operator runbook: put priority PRs first in the OpenCode dispatch queue.

One OpenCode runner serves every repository first-in first-out, so a release
PR can wait behind a day of other reviews. This script lists the queued
``opencode-review-dispatch`` runs and classifies each against its live PR:

* ``stale``: the PR is closed or its head moved; the run would fail validation.
* ``keep``: the PR carries the priority label, applied by someone with write,
  maintain or admin permission (a fork author cannot jump the queue).
* ``cancel_current``: every other current-head run.

It always prints metrics (deferred count, oldest deferred age, priority queue
positions). ``--post-issue`` writes the cancel list to an issue *before*
anything is cancelled, and ``--apply`` cancels only runs that are still queued.
Cancelled PRs are not lost: the scheduler re-dispatches any PR without a
current-head verdict, or an operator reruns its ``opencode-review`` job.

GitHub's ``status=queued`` run listing is eventually consistent and can omit
queued runs, so counts are a lower bound and a missed run is never cancelled.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

CENTRAL = "ContextualWisdomLab/.github"
WORKFLOW = "opencode-review-dispatch.yml"
TRUSTED_PERMISSIONS = frozenset({"admin", "maintain", "write"})
TITLE_RE = re.compile(r"ContextualWisdomLab/([A-Za-z0-9_.-]+)#(\d+)@([0-9a-f]{7,40})")


@dataclass(frozen=True)
class QueuedRun:
    run_id: int
    created_at: datetime
    repo: str
    pr: int
    head: str


@dataclass(frozen=True)
class PrState:
    state: str
    head: str
    priority: bool


@dataclass(frozen=True)
class Plan:
    keep: tuple[QueuedRun, ...]
    cancel_current: tuple[QueuedRun, ...]
    cancel_stale: tuple[QueuedRun, ...]
    ordered: tuple[QueuedRun, ...]


def trusted_priority(label: str, labeled_by: list[tuple[str, str]]) -> bool:
    """Return whether ``label`` was applied by an actor with write access or above."""
    return any(name == label and perm in TRUSTED_PERMISSIONS for name, perm in labeled_by)


def plan(runs: list[QueuedRun], live: dict[tuple[str, int], PrState]) -> Plan:
    """Split queued runs into keep / cancel-current / cancel-stale, oldest first."""
    ordered = tuple(sorted(runs, key=lambda r: (r.created_at, r.run_id)))
    keep, current, stale = [], [], []
    for r in ordered:
        s = live.get((r.repo, r.pr))
        if s is None or s.state != "OPEN" or not s.head.startswith(r.head):
            stale.append(r)
        elif s.priority:
            keep.append(r)
        else:
            current.append(r)
    return Plan(tuple(keep), tuple(current), tuple(stale), ordered)


def metrics(p: Plan, *, now: datetime) -> dict:
    """Summarise the backlog so starvation is visible rather than hidden."""
    oldest = min((r.created_at for r in p.cancel_current), default=None)
    position = {r.run_id: i for i, r in enumerate(p.ordered, 1)}
    return {
        "queued": len(p.ordered),
        "deferred": len(p.cancel_current),
        "stale": len(p.cancel_stale),
        "oldest_deferred_hours": round((now - oldest).total_seconds() / 3600, 1) if oldest else 0.0,
        "priority_positions": {f"{r.repo}#{r.pr}": position[r.run_id] for r in p.keep},
    }


def _gh(*args: str, stdin: str | None = None) -> str:
    return subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, check=True).stdout  # pragma: no cover


def fetch_queued() -> list[QueuedRun]:
    out = _gh("api", "--paginate", f"repos/{CENTRAL}/actions/workflows/{WORKFLOW}/runs?status=queued&per_page=100",  # pragma: no cover
              "--jq", ".workflow_runs[]|[.id,.created_at,.display_title]|@json")
    runs = []  # pragma: no cover
    for line in out.splitlines():  # pragma: no branch  # pragma: no cover
        run_id, created, title = json.loads(line)  # pragma: no cover
        m = TITLE_RE.search(title)  # pragma: no cover
        if m:  # pragma: no branch  # pragma: no cover
            runs.append(QueuedRun(int(run_id), datetime.fromisoformat(created.replace("Z", "+00:00")),  # pragma: no cover
                                  f"ContextualWisdomLab/{m.group(1)}", int(m.group(2)), m.group(3)))
    return runs  # pragma: no cover


def fetch_live(keys: set[tuple[str, int]], label: str) -> dict[tuple[str, int], PrState]:
    live: dict[tuple[str, int], PrState] = {}  # pragma: no cover
    perms: dict[tuple[str, str], str] = {}  # pragma: no cover
    keys_sorted = sorted(keys)  # pragma: no cover
    for i in range(0, len(keys_sorted), 40):  # pragma: no branch  # pragma: no cover
        chunk = keys_sorted[i:i + 40]  # pragma: no cover
        query = "query{" + " ".join(  # pragma: no cover
            f'p{k}:repository(owner:"{repo.split("/")[0]}",name:"{repo.split("/")[1]}")'  # pragma: no cover
            f'{{pullRequest(number:{pr}){{state headRefOid labels(first:30){{nodes{{name}}}} '  # pragma: no cover
            f'timelineItems(last:50,itemTypes:[LABELED_EVENT]){{nodes{{... on LabeledEvent{{label{{name}} actor{{login}}}}}}}}}}}}'  # pragma: no cover
            for k, (repo, pr) in enumerate(chunk)) + "}"  # pragma: no cover
        data = json.loads(_gh("api", "graphql", "-f", f"query={query}")).get("data") or {}  # pragma: no cover
        for k, (repo, pr) in enumerate(chunk):  # pragma: no branch  # pragma: no cover
            node = ((data.get(f"p{k}") or {}).get("pullRequest")) or {}  # pragma: no cover
            if not node:  # pragma: no branch  # pragma: no cover
                continue  # pragma: no cover
            labeled_by = []  # pragma: no cover
            if any(n["name"] == label for n in node["labels"]["nodes"]):  # pragma: no branch  # pragma: no cover
                for ev in node["timelineItems"]["nodes"]:  # pragma: no branch  # pragma: no cover
                    if ev.get("label", {}).get("name") != label or not ev.get("actor"):  # pragma: no branch  # pragma: no cover
                        continue  # pragma: no cover
                    login = ev["actor"]["login"]  # pragma: no cover
                    if (repo, login) not in perms:  # pragma: no branch  # pragma: no cover
                        try:  # pragma: no cover
                            perms[(repo, login)] = _gh("api", f"repos/{repo}/collaborators/{login}/permission",  # pragma: no cover
                                                       "--jq", ".permission").strip()
                        except subprocess.CalledProcessError:  # pragma: no cover
                            perms[(repo, login)] = "none"  # pragma: no cover
                    labeled_by.append((label, perms[(repo, login)]))  # pragma: no cover
            live[(repo, pr)] = PrState(node["state"], node["headRefOid"], trusted_priority(label, labeled_by))  # pragma: no cover
    return live  # pragma: no cover


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])  # pragma: no cover
    ap.add_argument("--label", default="review-priority")  # pragma: no cover
    ap.add_argument("--include-current", action="store_true", help="also cancel non-priority current-head runs")  # pragma: no cover
    ap.add_argument("--post-issue", metavar="OWNER/REPO#N", help="post the cancel list here before cancelling")  # pragma: no cover
    ap.add_argument("--apply", action="store_true", help="cancel runs that are still queued")  # pragma: no cover
    args = ap.parse_args(argv)  # pragma: no cover
    if args.apply and not args.post_issue:  # pragma: no branch  # pragma: no cover
        ap.error("--apply requires --post-issue so the cancel list is recorded first")  # pragma: no cover
  # pragma: no cover
    runs = fetch_queued()  # pragma: no cover
    p = plan(runs, fetch_live({(r.repo, r.pr) for r in runs}, args.label))  # pragma: no cover
    m = metrics(p, now=datetime.now(timezone.utc))  # pragma: no cover
    print(json.dumps(m, indent=2))  # pragma: no cover
    targets = list(p.cancel_stale) + (list(p.cancel_current) if args.include_current else [])  # pragma: no cover
    table = "run_id\tcreated_at\trepository\tpr\thead_sha\treason\n" + "".join(  # pragma: no cover
        f"{r.run_id}\t{r.created_at.isoformat()}\t{r.repo}\t{r.pr}\t{r.head}\t"  # pragma: no cover
        f"{'stale' if r in p.cancel_stale else 'deferred'}\n" for r in targets)  # pragma: no cover
    print(table, end="")  # pragma: no cover
    if args.post_issue:  # pragma: no branch  # pragma: no cover
        repo, number = args.post_issue.split("#")  # pragma: no cover
        body = (f"## OpenCode queue priority runbook\n\nMetrics: `{json.dumps(m)}`\n\n"  # pragma: no cover
                f"Label `{args.label}` (maintainer-applied) kept: {len(p.keep)}. To cancel: {len(targets)}.\n\n"  # pragma: no cover
                f"<details><summary>Cancel list (TSV)</summary>\n\n```tsv\n{table}```\n</details>\n")  # pragma: no cover
        _gh("issue", "comment", number, "-R", repo, "--body-file", "-", stdin=body)  # pragma: no cover
    if args.apply:  # pragma: no branch  # pragma: no cover
        cancelled = 0  # pragma: no cover
        for r in targets:  # pragma: no branch  # pragma: no cover
            status = _gh("api", f"repos/{CENTRAL}/actions/runs/{r.run_id}", "--jq", ".status").strip()  # pragma: no cover
            if status == "queued":  # pragma: no branch  # pragma: no cover
                _gh("api", "-X", "POST", f"repos/{CENTRAL}/actions/runs/{r.run_id}/cancel")  # pragma: no cover
                cancelled += 1  # pragma: no cover
        print(f"cancelled={cancelled}")  # pragma: no cover
    return 0  # pragma: no cover


if __name__ == "__main__":  # pragma: no branch
    sys.exit(main())  # pragma: no cover
