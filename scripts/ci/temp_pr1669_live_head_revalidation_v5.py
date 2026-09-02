#!/usr/bin/env python3
"""Publish PR #1669 from the current protected-main scheduler shape.

This one-shot helper exists only because the older generated repair used brittle
whole-fragment anchors and failed after protected main moved. It deliberately
records RED before changing production code, applies the repair by Python
function boundaries, updates durable incident evidence, and then deletes every
one-shot artifact including itself.
"""

from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SCHEDULER = ROOT / "scripts/ci/pr_review_merge_scheduler.py"
TESTS = ROOT / "tests/test_pr_review_merge_scheduler.py"
DOCTORING = ROOT / "docs/doctoring/scheduler-stale-headrefoid-cancellation.md"
BASELINE = ROOT / "docs/product-technical-gap-baseline.md"
CHANGELOG = ROOT / "CHANGELOG.md"
SELF = Path(__file__).resolve()
TEMP_PATHS = (
    ROOT / ".github/workflows/_temp_pr1669_live_head_revalidation_repair.yml",
    ROOT / "scripts/ci/temp_pr1669_live_head_revalidation_repair.py",
    ROOT / "scripts/ci/temp_pr1669_live_head_revalidation_v2.py",
    ROOT / "scripts/ci/temp_pr1669_live_head_revalidation_v3.py",
    ROOT / "scripts/ci/temp_pr1669_live_head_revalidation_v4.py",
    SELF,
)


def function_span(text: str, name: str) -> tuple[int, int]:
    """Return zero-based start and exclusive end line indexes for a function."""
    tree = ast.parse(text)
    matches = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one function {name!r}, found {len(matches)}")
    node = matches[0]
    if node.end_lineno is None:
        raise RuntimeError(f"function {name!r} has no end line")
    return node.lineno - 1, node.end_lineno


def replace_in_function(text: str, name: str, old: str, new: str) -> str:
    """Replace one fragment only inside a named top-level function."""
    lines = text.splitlines(keepends=True)
    start, end = function_span(text, name)
    segment = "".join(lines[start:end])
    if segment.count(old) != 1:
        raise RuntimeError(
            f"{name}: expected one repair anchor {old!r}, found {segment.count(old)}"
        )
    segment = segment.replace(old, new, 1)
    return "".join(lines[:start]) + segment + "".join(lines[end:])


def replace_function_range(text: str, first_name: str, last_name: str, replacement: str) -> str:
    """Replace an adjacent top-level function range using AST line boundaries."""
    lines = text.splitlines(keepends=True)
    first_start, _ = function_span(text, first_name)
    _, last_end = function_span(text, last_name)
    if first_start >= last_end:
        raise RuntimeError("invalid function replacement range")
    return "".join(lines[:first_start]) + replacement.rstrip() + "\n\n\n" + "".join(lines[last_end:])


def insert_after_test_def(text: str, name: str, code: str) -> str:
    """Insert one compatibility monkeypatch after a named test definition."""
    anchor = f"def {name}(monkeypatch):\n"
    if anchor + code in text:
        return text
    if text.count(anchor) != 1:
        raise RuntimeError(f"test anchor {name!r}: expected one definition")
    return text.replace(anchor, anchor + code, 1)


REGRESSION_TESTS = r'''


def test_pr1669_malformed_snapshot_head_never_classifies_direct_run_stale(monkeypatch):
    """Malformed snapshot head authority cannot classify a valid active run stale."""
    monkeypatch.setattr(
        sched,
        "active_workflow_runs",
        lambda *_args, **_kwargs: [
            {"id": 33581213829, "head_sha": "a" * 40, "pull_requests": [{"number": 1528}]}
        ],
    )
    assert sched.stale_pr_run_ids(
        "ContextualWisdomLab/naruon",
        make_pr(number=1528, headRefOid="malformed-but-truthy"),
    ) == []


def test_pr1669_malformed_snapshot_head_never_classifies_review_run_stale(monkeypatch):
    """Malformed snapshot head authority cannot classify central review runs stale."""
    monkeypatch.setattr(
        sched,
        "active_workflow_runs",
        lambda *_args, **_kwargs: [
            {
                "id": 33581213829,
                "event": "pull_request",
                "name": "OpenCode Review",
                "head_sha": "a" * 40,
                "pull_requests": [{"number": 1528}],
            }
        ],
    )
    assert sched.active_review_run_refs(
        "ContextualWisdomLab/naruon",
        "OpenCode Review",
        make_pr(number=1528, headRefOid="malformed-but-truthy"),
        run_title="Required OpenCode Review",
        workflow_aliases=frozenset(sched.OPENCODE_WORKFLOW_NAMES),
    ) == ([], [])


def test_pr1669_snapshot_race_preserves_new_current_head(monkeypatch):
    """A push after classification cannot make the new current-head run cancellable."""
    old_head, new_head = "a" * 40, "b" * 40
    candidate = {
        "id": 77,
        "event": "pull_request",
        "status": "queued",
        "head_sha": new_head,
        "pull_requests": [{"number": 7}],
    }
    monkeypatch.setattr(sched, "stale_pr_run_ids", lambda *_args, **_kwargs: ["77"])
    monkeypatch.setattr(sched, "require_github_actions_control_actor", lambda _action: None)
    calls = []

    def fake_api(path):
        calls.append(path)
        if path.endswith("/actions/runs/77"):
            return candidate
        return {"state": "open", "draft": False, "head": {"sha": new_head}}

    cancelled = []
    monkeypatch.setattr(sched, "gh_api_json", fake_api)
    monkeypatch.setattr(
        sched,
        "force_cancel_workflow_runs",
        lambda *_args: cancelled.append(_args),
    )
    assert sched.cancel_stale_pr_runs(
        "owner/repo", make_pr(number=7, headRefOid=old_head), dry_run=False
    ) == []
    assert cancelled == []
    assert calls[-1] == "repos/owner/repo/pulls/7"


@pytest.mark.parametrize(
    "live_pr",
    [
        None,
        {"state": "closed", "draft": False, "head": {"sha": "b" * 40}},
        {"state": "open", "draft": True, "head": {"sha": "b" * 40}},
        {"state": "open", "draft": None, "head": {"sha": "b" * 40}},
        {"state": "open", "draft": False, "head": {"sha": "bad"}},
    ],
)
def test_pr1669_fresh_open_pr_fails_closed_without_ready_exact_head(monkeypatch, live_pr):
    """Only an open, explicitly ready PR with a valid SHA grants cancellation authority."""
    monkeypatch.setattr(sched, "gh_api_json", lambda _path: live_pr)
    with pytest.raises(ValueError):
        sched._fresh_open_pr_for_cancellation("owner/repo", 7)


@pytest.mark.parametrize("payload", [None, {"status": "completed"}])
def test_pr1669_fresh_active_run_requires_active_mapping(monkeypatch, payload):
    """Only a freshly active run mapping can authorize destructive cancellation."""
    monkeypatch.setattr(sched, "gh_api_json", lambda _path: payload)
    with pytest.raises(ValueError, match="is not active"):
        sched._fresh_active_run_for_cancellation("owner/repo", "94")


@pytest.mark.parametrize(
    "run",
    [
        {
            "event": "repository_dispatch",
            "status": "queued",
            "head_sha": "a" * 40,
            "pull_requests": [{"number": 7}],
        },
        {
            "event": "pull_request",
            "status": "queued",
            "head_sha": "a" * 40,
            "pull_requests": [{"number": 8}],
        },
    ],
)
def test_pr1669_direct_revalidation_rejects_changed_run_identity(monkeypatch, run):
    """A direct candidate must remain a direct run attached to the target PR."""
    monkeypatch.setattr(
        sched,
        "gh_api_json",
        lambda path: run
        if "/actions/runs/" in path
        else {"state": "open", "draft": False, "head": {"sha": "b" * 40}},
    )
    assert sched._direct_pr_run_still_superseded("owner/repo", 7, "93") is False


def test_pr1669_direct_revalidation_allows_genuine_supersession(monkeypatch):
    """A genuinely older direct PR run remains cancellable after fresh reads."""
    monkeypatch.setattr(
        sched,
        "gh_api_json",
        lambda path: {
            "event": "pull_request",
            "status": "in_progress",
            "head_sha": "a" * 40,
            "pull_requests": [{"number": 7}],
        }
        if "/actions/runs/" in path
        else {"state": "open", "draft": False, "head": {"sha": "b" * 40}},
    )
    assert sched._direct_pr_run_still_superseded("owner/repo", 7, "98") is True


def test_pr1669_review_target_rejects_untrusted_dispatch_title():
    """A central dispatch without exact target identity has no cancellation authority."""
    with pytest.raises(ValueError, match="trusted target identity"):
        sched._review_run_target_head(
            {"event": "repository_dispatch", "display_title": "unrelated"},
            "owner/repo",
            "OpenCode Review",
            7,
        )


def test_pr1669_review_target_rejects_changed_direct_pr_association():
    """A direct review run must remain attached to the target pull request."""
    with pytest.raises(ValueError, match="target pull request"):
        sched._review_run_target_head(
            {
                "event": "pull_request",
                "head_sha": "a" * 40,
                "pull_requests": [{"number": 8}],
            },
            "owner/repo",
            "OpenCode Review",
            7,
        )


def test_pr1669_review_target_accepts_direct_and_trusted_dispatch_identity():
    """Direct and trusted central review identities expose validated target heads."""
    assert sched._review_run_target_head(
        {
            "event": "pull_request",
            "head_sha": "a" * 40,
            "pull_requests": [{"number": 7}],
        },
        "owner/repo",
        "OpenCode Review",
        7,
    ) == "a" * 40
    assert sched._review_run_target_head(
        {
            "event": "repository_dispatch",
            "display_title": f"Required OpenCode Review owner/repo#7@{'a' * 40}",
        },
        "owner/repo",
        "OpenCode Review",
        7,
    ) == "a" * 40


def test_pr1669_review_revalidation_handles_stale_and_current_heads(monkeypatch):
    """Fresh review authority distinguishes genuine supersession from the current head."""
    run = {
        "event": "repository_dispatch",
        "status": "in_progress",
        "display_title": f"Required OpenCode Review owner/repo#7@{'a' * 40}",
    }
    live_head = {"value": "b" * 40}

    def fake_api(path):
        if "/actions/runs/" in path:
            return run
        return {"state": "open", "draft": False, "head": {"sha": live_head["value"]}}

    monkeypatch.setattr(sched, "gh_api_json", fake_api)
    assert sched._review_run_still_superseded(
        "owner/repo", "OpenCode Review", 7, "ContextualWisdomLab/.github", "95"
    ) is True
    live_head["value"] = "a" * 40
    assert sched._review_run_still_superseded(
        "owner/repo", "OpenCode Review", 7, "ContextualWisdomLab/.github", "95"
    ) is False


def test_pr1669_single_direct_candidate_cancels_only_when_revalidated_stale(monkeypatch):
    """The direct single-candidate path preserves current and cancels proven stale runs."""
    monkeypatch.setattr(sched, "require_github_actions_control_actor", lambda _action: None)
    monkeypatch.setattr(sched, "stale_pr_run_ids", lambda *_args, **_kwargs: ["97"])
    stale = {"value": False}
    monkeypatch.setattr(sched, "_direct_pr_run_still_superseded", lambda *_args: stale["value"])
    cancelled = []
    monkeypatch.setattr(
        sched,
        "force_cancel_workflow_runs",
        lambda repo, run_ids: cancelled.append((repo, run_ids)),
    )
    pr = make_pr(number=7)
    assert sched.cancel_stale_pr_runs("owner/repo", pr, dry_run=False) == []
    stale["value"] = True
    assert sched.cancel_stale_pr_runs("owner/repo", pr, dry_run=False) == ["97"]
    assert cancelled == [("owner/repo", ["97"])]


def test_pr1669_single_review_candidate_cancels_only_when_revalidated_stale(monkeypatch):
    """The review single-candidate path preserves current and cancels proven stale runs."""
    monkeypatch.setattr(sched, "require_github_actions_control_actor", lambda _action: None)
    monkeypatch.setattr(
        sched,
        "active_opencode_run_refs",
        lambda *_args, **_kwargs: ([], [("ContextualWisdomLab/.github", "96")]),
    )
    stale = {"value": False}
    monkeypatch.setattr(sched, "_review_run_still_superseded", lambda *_args: stale["value"])
    cancelled = []
    monkeypatch.setattr(
        sched,
        "force_cancel_workflow_runs",
        lambda repo, run_ids: cancelled.append((repo, run_ids)),
    )
    pr = make_pr(number=7)
    assert sched.cancel_stale_opencode_runs(
        "owner/repo", "OpenCode Review", pr, dry_run=False
    ) == []
    stale["value"] = True
    assert sched.cancel_stale_opencode_runs(
        "owner/repo", "OpenCode Review", pr, dry_run=False
    ) == ["96"]
    assert cancelled == [("ContextualWisdomLab/.github", ["96"])]
'''


CANCELLATION_IMPLEMENTATION = r'''def _fresh_open_pr_for_cancellation(repo: str, number: int) -> dict[str, Any]:
    """Return fresh, still-open and explicitly ready pull-request authority."""
    payload = gh_api_json(f"repos/{repo}/pulls/{number}")
    if not isinstance(payload, dict) or str(payload.get("state") or "").lower() != "open":
        raise ValueError(f"PR #{number} in {repo} is not a resolvable open pull request")
    if payload.get("draft") is not False:
        raise ValueError(f"PR #{number} in {repo} is not live ready-for-review authority")
    validate_git_sha(str(((payload.get("head") or {}).get("sha")) or ""))
    return payload


def _fresh_active_run_for_cancellation(run_repo: str, run_id: str) -> dict[str, Any]:
    """Return fresh active workflow-run evidence immediately before cancellation."""
    payload = gh_api_json(f"repos/{run_repo}/actions/runs/{run_id}")
    if not isinstance(payload, dict) or str(payload.get("status") or "").lower() not in {
        "queued",
        "in_progress",
    }:
        raise ValueError(f"workflow run {run_repo}#{run_id} is not active")
    return payload


def _fresh_pr_head_for_cancellation(repo: str, number: int) -> str:
    """Return the validated head SHA from fresh ready/open PR authority."""
    payload = _fresh_open_pr_for_cancellation(repo, number)
    return validate_git_sha(str(((payload.get("head") or {}).get("sha")) or "")).lower()


def _direct_pr_run_still_superseded(repo: str, number: int, run_id: str) -> bool:
    """Return whether a direct PR run is still older than the freshly fetched live head."""
    try:
        run_data = _fresh_active_run_for_cancellation(repo, run_id)
        if run_data.get("event") == "repository_dispatch" or not workflow_run_mentions_pr(
            run_data, number
        ):
            raise ValueError("workflow run no longer has direct pull-request authority")
        run_head = validate_git_sha(str(run_data.get("head_sha") or "")).lower()
        live_head = _fresh_pr_head_for_cancellation(repo, number)
    except (KeyError, RuntimeError, TypeError, ValueError) as exc:
        print(
            f"::warning::Preserving workflow run {run_id} in {repo}: "
            f"live stale-run revalidation failed closed ({exc})."
        )
        return False
    return run_head != live_head


def _review_run_target_head(
    run_data: dict[str, Any], repo: str, workflow: str, number: int
) -> str:
    """Return a validated target head for one direct or trusted central review run."""
    if run_data.get("event") == "repository_dispatch":
        titles = {"Required OpenCode Review", workflow, *OPENCODE_WORKFLOW_NAMES}
        display_title = str(run_data.get("display_title") or "")
        prefixes = tuple(
            f"{title} {repo}#{number}@" for title in sorted(titles, key=len, reverse=True)
        )
        prefix = next((candidate for candidate in prefixes if display_title.startswith(candidate)), None)
        if prefix is None:
            raise ValueError("repository_dispatch run has no trusted target identity")
        return validate_git_sha(display_title.removeprefix(prefix)).lower()
    if not workflow_run_mentions_pr(run_data, number):
        raise ValueError("review run no longer belongs to the target pull request")
    return validate_git_sha(str(run_data.get("head_sha") or "")).lower()


def _review_run_still_superseded(
    repo: str,
    workflow: str,
    number: int,
    run_repo: str,
    run_id: str,
) -> bool:
    """Return whether one review run remains stale against fresh ready/open PR authority."""
    try:
        run_data = _fresh_active_run_for_cancellation(run_repo, run_id)
        run_head = _review_run_target_head(run_data, repo, workflow, number)
        live_head = _fresh_pr_head_for_cancellation(repo, number)
    except (KeyError, RuntimeError, TypeError, ValueError) as exc:
        print(
            f"::warning::Preserving review run {run_repo}#{run_id}: "
            f"live stale-run revalidation failed closed ({exc})."
        )
        return False
    return run_head != live_head


def cancel_stale_pr_runs(repo: str, pr: dict[str, Any], *, dry_run: bool) -> list[str]:
    """Force-cancel only direct-run candidates still proven stale at the destructive boundary."""
    if dry_run:
        return []
    require_github_actions_control_actor("force-cancel-stale-pr-runs")
    number = int(pr["number"])
    candidates = [str(run_id) for run_id in stale_pr_run_ids(repo, pr)]

    def cancel_one(run_id: str) -> str | None:
        """Revalidate and cancel one direct workflow-run candidate when still stale."""
        if not _direct_pr_run_still_superseded(repo, number, run_id):
            return None
        force_cancel_workflow_runs(repo, [run_id])
        return run_id

    if len(candidates) <= 1:
        results = [cancel_one(run_id) for run_id in candidates]
    else:
        max_workers = min(REST_MERGEABLE_STATE_WORKERS, len(candidates))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(cancel_one, candidates))
    return [run_id for run_id in results if run_id is not None]


def cancel_stale_opencode_runs(repo: str, workflow: str, pr: dict[str, Any], *, dry_run: bool) -> list[str]:
    """Force-cancel only review candidates still proven stale at the destructive boundary."""
    if dry_run:
        return []
    require_github_actions_control_actor("force-cancel-stale-opencode-review")
    number = int(pr["number"])
    _, stale_refs = active_opencode_run_refs(repo, workflow, pr)

    def cancel_one(run_ref: tuple[str, str]) -> str | None:
        """Revalidate and cancel one review-run candidate when still stale."""
        run_repo, run_id = run_ref
        if not _review_run_still_superseded(repo, workflow, number, run_repo, run_id):
            return None
        force_cancel_workflow_runs(run_repo, [run_id])
        return run_id

    if len(stale_refs) <= 1:
        results = [cancel_one(run_ref) for run_ref in stale_refs]
    else:
        max_workers = min(REST_MERGEABLE_STATE_WORKERS, len(stale_refs))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(cancel_one, stale_refs))
    return [run_id for run_id in results if run_id is not None]
'''


def add_regressions_and_record_red() -> None:
    """Install regressions first and require the unmodified production code to fail them."""
    text = TESTS.read_text(encoding="utf-8")
    marker = "def test_pr1669_malformed_snapshot_head_never_classifies_direct_run_stale"
    if marker in text:
        raise RuntimeError("PR1669 v5 regressions already present on input head")
    text += REGRESSION_TESTS
    TESTS.write_text(text, encoding="utf-8")
    red = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_pr_review_merge_scheduler.py",
            "-q",
            "-k",
            "pr1669_malformed_snapshot_head_never_classifies_direct_run_stale or pr1669_snapshot_race_preserves_new_current_head",
        ],
        cwd=ROOT,
        check=False,
    )
    if red.returncode == 0:
        raise RuntimeError("PR1669 RED regressions unexpectedly passed before the production repair")
    print(f"PR1669_RED_CONFIRMED pytest_exit={red.returncode}")


def repair_source() -> None:
    """Apply validated-head classification and destructive-boundary live revalidation."""
    text = SCHEDULER.read_text(encoding="utf-8")
    guard_direct = '''    raw_head = pr.get("headRefOid")
    try:
        head = validate_git_sha(str(raw_head or "")).lower()
    except (TypeError, ValueError) as exc:
        print(
            f"::warning::stale_pr_run_ids: PR #{pr.get('number')} in {repo} has an "
            f"invalid or unresolved headRefOid; preserving active runs ({exc})."
        )
        return []
'''
    guard_review = '''    raw_head = pr.get("headRefOid")
    try:
        head = validate_git_sha(str(raw_head or "")).lower()
    except (TypeError, ValueError) as exc:
        print(
            f"::warning::active_review_run_refs: PR #{pr.get('number')} in {target_repo} has an "
            f"invalid or unresolved headRefOid; preserving review runs ({exc})."
        )
        return [], []
'''
    text = replace_in_function(
        text,
        "stale_pr_run_ids",
        '    head = str(pr.get("headRefOid") or "").lower()\n',
        guard_direct,
    )
    text = replace_in_function(
        text,
        "active_review_run_refs",
        '    head = str(pr.get("headRefOid") or "").lower()\n',
        guard_review,
    )
    for helper_name in (
        "_fresh_open_pr_for_cancellation",
        "_fresh_active_run_for_cancellation",
        "_fresh_pr_head_for_cancellation",
        "_direct_pr_run_still_superseded",
        "_review_run_target_head",
        "_review_run_still_superseded",
    ):
        if any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == helper_name
            for node in ast.parse(text).body
        ):
            raise RuntimeError(f"unexpected pre-existing helper {helper_name}")
    text = replace_function_range(
        text,
        "cancel_stale_pr_runs",
        "cancel_stale_opencode_runs",
        CANCELLATION_IMPLEMENTATION,
    )
    SCHEDULER.write_text(text, encoding="utf-8")


def preserve_legacy_test_intent() -> None:
    """Keep legacy synthetic fixtures focused on their original bounded behavior."""
    text = TESTS.read_text(encoding="utf-8")
    text = insert_after_test_def(
        text,
        "test_cancel_stale_pr_runs_force_cancels_queued_and_in_progress_old_heads",
        '    monkeypatch.setattr(sched, "_direct_pr_run_still_superseded", lambda *_args: True)\n',
    )
    text = insert_after_test_def(
        text,
        "test_cancel_stale_opencode_runs_uses_bounded_executor_for_multiple_runs",
        '    monkeypatch.setattr(sched, "_review_run_still_superseded", lambda *_args: True)\n',
    )
    for name in (
        "test_stale_opencode_run_ids_filters_current_head_and_missing_ids",
        "test_workflow_run_filters_skip_mismatched_workflow_and_current_head_other_pr",
    ):
        text = insert_after_test_def(
            text,
            name,
            '    monkeypatch.setattr(sched, "validate_git_sha", lambda value: str(value))\n',
        )
    TESTS.write_text(text, encoding="utf-8")


def write_durable_evidence() -> None:
    """Record incident RCA and material control-plane status in durable repository docs."""
    DOCTORING.write_text(
        """# Scheduler stale-head cancellation: fail closed at the destructive boundary\n\n"
        "## Incident\n\n"
        "On 2026-09-02, `ContextualWisdomLab/naruon#1528` had Strix run "
        "`33581213829` cancelled while its head `cf472cf77fb93325858f485a22e967449d7c387a` "
        "was still the PR's sole current head. The run-local Strix supersession job was skipped; "
        "the shared merge scheduler remained a separate cancellation authority.\n\n"
        "## Root cause\n\n"
        "`stale_pr_run_ids()` and `active_review_run_refs()` converted an unresolved `headRefOid` "
        "to an empty string. Every real run SHA then compared unequal and became a stale candidate. "
        "The destructive cancellation functions trusted that earlier snapshot and did not re-read "
        "the candidate run and live PR immediately before cancellation.\n\n"
        "## Repair contract\n\n"
        "- Snapshot heads are validated with the canonical 40-hex SHA validator. Missing or malformed "
        "heads preserve all active runs.\n"
        "- Every direct and central-review cancellation candidate is re-read from GitHub immediately "
        "before cancellation.\n"
        "- The live PR must still be open, explicitly non-draft, and expose a valid head SHA.\n"
        "- The candidate run must still be queued/in-progress and still carry the expected direct PR "
        "association or trusted central dispatch title.\n"
        "- If the candidate now matches the live head, or any identity/state read is malformed or "
        "unavailable, cancellation fails closed and preserves the run.\n"
        "- Genuine older-head runs remain cancellable, including the multi-candidate bounded executor path.\n\n"
        "This aligns the Python scheduler path with the existing queue-hygiene live-reference race "
        "contract in `scripts/ci/revalidate_queue_cancellation.sh`.\n\n"
        "## Verification\n\n"
        "The repair is test-first: exact regressions are installed and required to fail before the "
        "production transformation. The final one-shot verifier then runs the focused scheduler suite, "
        "the complete repository suite with 100% statement/branch coverage, 100% `scripts/ci` docstring "
        "coverage, compileall, and diff hygiene before publication. The one-shot workflow and every "
        "temporary repair driver delete themselves from the published successor.\n"
        """,
        encoding="utf-8",
    )
    changelog = CHANGELOG.read_text(encoding="utf-8")
    bullet = (
        "- **Fail closed before cancelling stale PR workflow runs.** Validate snapshot `headRefOid` "
        "and re-read live PR/run identity immediately before destructive cancellation so a missing "
        "head or concurrent push cannot cancel the sole current-head evidence; preserve genuine "
        "older-head cancellation and retire the one-shot repair lane after verification.\n"
    )
    if bullet not in changelog:
        changelog = changelog.replace("## [Unreleased]\n", "## [Unreleased]\n" + bullet, 1)
        CHANGELOG.write_text(changelog, encoding="utf-8")
    baseline = BASELINE.read_text(encoding="utf-8")
    marker = "## 2026-09-02 scheduler destructive-boundary stale-run repair"
    if marker not in baseline:
        baseline += (
            "\n\n" + marker + "\n\n"
            "A live naruon incident proved the shared merge scheduler could classify every active "
            "run as stale when `headRefOid` was unresolved, then cancel from stale snapshot authority. "
            "The canonical owner repair validates snapshot SHA evidence and revalidates live PR/run "
            "identity at the destructive boundary, failing closed on draft/closed/malformed/unavailable "
            "authority while retaining cancellation of genuinely superseded heads. Regression evidence "
            "covers the original incident shape, concurrent-push race, direct and central review identity, "
            "and positive supersession. The temporary writer/workflow is removed from the final tree.\n"
        )
        BASELINE.write_text(baseline, encoding="utf-8")


def delete_one_shot_artifacts() -> None:
    """Remove every temporary driver and the one-shot workflow from the final tree."""
    for path in TEMP_PATHS:
        if path.exists():
            path.unlink()


def main() -> int:
    """Execute RED, repair, durable evidence, and one-shot artifact retirement."""
    add_regressions_and_record_red()
    repair_source()
    preserve_legacy_test_intent()
    write_durable_evidence()
    delete_one_shot_artifacts()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
