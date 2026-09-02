"""Finish PR #1706 exact-run wake repair after the first deterministic driver.

Temporary helper: the source-fix workflow deletes this file in the successful
publication commit together with the other PR #1706 repair machinery.
"""

from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/opencode-review.yml")
DISPATCH = Path(".github/workflows/opencode-review-dispatch.yml")
ACCEPTANCE = Path("tests/test_opencode_required_verdict_runner_release.py")
REGRESSION = Path("tests/test_opencode_required_verdict_regression.py")
SELF = Path("tests/test_opencode_poll_self_retirement.py")
LIVE_DRAFT = Path("tests/test_opencode_live_draft_state_regression.py")
ARCHITECTURE = Path("ARCHITECTURE.md")
DOCTORING = Path("docs/doctoring/opencode-stale-poll-self-retirement.md")
CHANGELOG = Path("CHANGELOG.md")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact fragment and fail closed when concurrent edits drift."""
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label} drifted: expected one exact match, found {count}")
    return text.replace(old, new, 1)


workflow = WORKFLOW.read_text(encoding="utf-8")
workflow = replace_once(
    workflow,
    '          live_pr="$(gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}")"\n',
    '          if ! live_pr="$(timeout 30s gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}")"; then\n'
    '            echo "::error::Live pull request API read failed during one-shot current-head verdict admission; failing closed and releasing the runner."\n'
    '            exit 1\n'
    '          fi\n',
    "bounded live PR read",
)
workflow = replace_once(
    workflow,
    '          if ! reviews="$(gh api --paginate "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews?per_page=100")"; then\n',
    '          if ! reviews="$(timeout 30s gh api --paginate "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews?per_page=100")"; then\n',
    "bounded Reviews read",
)
WORKFLOW.write_text(workflow, encoding="utf-8")

dispatch = DISPATCH.read_text(encoding="utf-8")
start = "      - name: Wake exact-head required OpenCode workflow\n"
end = "\n      - name: Publish repository_dispatch OpenCode status\n"
if dispatch.count(start) != 1 or dispatch.count(end) != 1:
    raise SystemExit("OpenCode exact-run wake boundaries drifted")
before, rest = dispatch.split(start, 1)
_old_wake, after = rest.split(end, 1)
wake = r'''      - name: Wake exact-head required OpenCode workflow
        if: >-
          always()
          && github.event_name == 'repository_dispatch'
          && steps.formal_review_receipt.outcome == 'success'
          && needs.validate-pr-metadata.outputs.target_repository != ''
          && needs.validate-pr-metadata.outputs.pr_number != ''
          && needs.validate-pr-metadata.outputs.head_sha != ''
          && github.event.client_payload.required_run_id != ''
        env:
          GH_TOKEN: ${{ needs.validate-pr-metadata.outputs.target_repository == github.repository && github.token || secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN }}
          GH_REPOSITORY: ${{ needs.validate-pr-metadata.outputs.target_repository }}
          PR_NUMBER: ${{ needs.validate-pr-metadata.outputs.pr_number }}
          PR_HEAD_SHA: ${{ needs.validate-pr-metadata.outputs.head_sha }}
          REQUIRED_RUN_ID: ${{ github.event.client_payload.required_run_id }}
          WAKE_TOKEN_SOURCE: ${{ needs.validate-pr-metadata.outputs.target_repository == github.repository && 'github-token' || secrets.PR_REVIEW_MERGE_TOKEN != '' && 'PR_REVIEW_MERGE_TOKEN' || secrets.OPENCODE_APPROVE_TOKEN != '' && 'OPENCODE_APPROVE_TOKEN' || 'unavailable' }}
        run: |
          set -euo pipefail
          if [ -z "${GH_TOKEN:-}" ] || [ "$WAKE_TOKEN_SOURCE" = "unavailable" ]; then
            echo "::error::Actions-capable wake credential is unavailable. Native runs use github.token; sibling runs require PR_REVIEW_MERGE_TOKEN or OPENCODE_APPROVE_TOKEN."
            exit 1
          fi
          [[ "$REQUIRED_RUN_ID" =~ ^[1-9][0-9]*$ ]] || { echo "::error::Required OpenCode run id is missing or non-canonical."; exit 1; }
          [[ "$PR_NUMBER" =~ ^[1-9][0-9]*$ ]] || { echo "::error::Required OpenCode PR number is missing or non-canonical."; exit 1; }
          [[ "$PR_HEAD_SHA" =~ ^[0-9a-fA-F]{40}$ ]] || { echo "::error::Required OpenCode PR head SHA is missing or malformed."; exit 1; }
          for attempt in $(seq 1 12); do
            if ! run="$(timeout 30s gh api "repos/${GH_REPOSITORY}/actions/runs/${REQUIRED_RUN_ID}")"; then
              echo "::warning::Exact required-run lookup attempt ${attempt}/12 failed; retrying before wake."
              if [ "$attempt" -lt 12 ]; then sleep 5; continue; fi
              break
            fi
            required_run="$(printf '%s\n' "$run" | jq -r --arg head "$PR_HEAD_SHA" --arg pr "$PR_NUMBER" --argjson run_id "$REQUIRED_RUN_ID" '
              select(.id == $run_id)
              | select(.event == "pull_request_target")
              | select(.path == ".github/workflows/opencode-review.yml")
              | select(any((.pull_requests // [])[]?; ((.number // 0) | tostring) == $pr and ((.head.sha // "") | ascii_downcase) == ($head | ascii_downcase)))
              | [(.id // ""), (.status // ""), (.conclusion // "")]
              | @tsv
            ')" || required_run=""
            if [ -z "$required_run" ]; then
              echo "::warning::Exact required-run lookup attempt ${attempt}/12 returned malformed or nonmatching evidence; retrying before wake."
              if [ "$attempt" -lt 12 ]; then sleep 5; continue; fi
              break
            fi
            IFS=$'\t' read -r required_run_id required_status required_conclusion <<<"$required_run"
            if [ "$required_status" = "completed" ] && [ "$required_conclusion" = "failure" ]; then
              gh api -X POST "repos/${GH_REPOSITORY}/actions/runs/${required_run_id}/rerun-failed-jobs" >/dev/null
              echo "Re-ran failed jobs for exact-PR/head Required OpenCode Review run ${required_run_id}."
              exit 0
            fi
            if [ "$required_status" = "completed" ] && [ "$required_conclusion" = "success" ]; then
              echo "Exact-PR/head Required OpenCode Review run ${required_run_id} already succeeded."
              exit 0
            fi
            if [ "$attempt" -lt 12 ]; then sleep 5; fi
          done
          echo "::error::Formal OpenCode receipt exists, but the exact-PR/head required workflow did not reach a rerunnable failed state."
          exit 1
'''
DISPATCH.write_text(before + wake + end + after, encoding="utf-8")

ACCEPTANCE.write_text(r'''"""Regression coverage for releasing the required OpenCode runner while review continues."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

WORKFLOW = Path(".github/workflows/opencode-review.yml")
DISPATCH_WORKFLOW = Path(".github/workflows/opencode-review-dispatch.yml")
HEAD_SHA = "a" * 40


def _fail_closed_script() -> str:
    """Extract only the real required-verdict admission run block."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = workflow.split("      - name: Fail closed without a current-head OpenCode verdict\n", 1)[1]
    block = step.split("        run: |\n", 1)[1].split("\n  cancel-superseded-opencode-review-runs:\n", 1)[0]
    return textwrap.dedent(block)


def _wake_script() -> str:
    """Extract only the exact-run wake shell body."""
    workflow = DISPATCH_WORKFLOW.read_text(encoding="utf-8")
    step = workflow.split("      - name: Wake exact-head required OpenCode workflow\n", 1)[1]
    block = step.split("        run: |\n", 1)[1].split("\n      - name: Publish repository_dispatch OpenCode status\n", 1)[0]
    return textwrap.dedent(block)


def test_missing_verdict_uses_exact_pr_run_wake_instead_of_runner_polling() -> None:
    """A missing verdict fails once and relies on authenticated exact-run wake."""
    required = _fail_closed_script()
    dispatched = DISPATCH_WORKFLOW.read_text(encoding="utf-8")
    for token in ("while :; do", "poll_interval_seconds", "poll_deadline_epoch", "sleep "):
        assert token not in required
    assert required.count("timeout 30s gh api") == 2
    assert "rerun-failed-jobs" in dispatched
    assert "pull_requests // []" in dispatched
    assert "(.number // 0) | tostring" in dispatched
    assert 'if ! run="$(timeout 30s gh api ' in dispatched


def _run_admission(tmp_path: Path, reviews: list[dict[str, object]]) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Execute production admission against deterministic live/review evidence."""
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    if bash is None or jq is None:
        pytest.skip("bash and jq are required")
    fake_gh = tmp_path / "gh"
    calls = tmp_path / "calls"
    fake_gh.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nprintf '%s\\n' \"$*\" >>\"$CALLS\"\n"
        "if [[ \"$*\" == \"api repos/ContextualWisdomLab/example/pulls/42\" ]]; then printf '%s\\n' \"$LIVE_PR\"; exit 0; fi\n"
        "if [[ \"$*\" == \"api --paginate repos/ContextualWisdomLab/example/pulls/42/reviews?per_page=100\" ]]; then printf '%s\\n' \"$REVIEWS\"; exit 0; fi\nexit 97\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    fake_timeout = tmp_path / "timeout"
    fake_timeout.write_text("#!/usr/bin/env bash\nset -euo pipefail\nshift\nexec \"$@\"\n", encoding="utf-8")
    fake_timeout.chmod(0o755)
    result = subprocess.run(
        [bash, "-c", _fail_closed_script()],
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}", "CALLS": str(calls), "LIVE_PR": json.dumps({"head": {"sha": HEAD_SHA}, "draft": False, "state": "open"}), "REVIEWS": json.dumps(reviews), "GH_TOKEN": "test-token", "TARGET_REPOSITORY": "ContextualWisdomLab/example", "PR_NUMBER": "42", "HEAD_SHA": HEAD_SHA, "PR_ACTION": "synchronize", "PR_DRAFT": "false"},
        text=True, capture_output=True, check=False,
    )
    return result, calls.read_text(encoding="utf-8").splitlines()


def test_missing_verdict_fails_after_one_live_and_one_review_read(tmp_path: Path) -> None:
    """No verdict releases the runner immediately with exactly two API reads."""
    result, calls = _run_admission(tmp_path, [])
    assert result.returncode == 1, result.stderr
    assert "No APPROVED or CHANGES_REQUESTED from opencode-agent" in result.stdout
    assert len(calls) == 2


def test_exact_run_wake_retries_transient_lookup_then_reruns_failed_job(tmp_path: Path) -> None:
    """A transient run lookup cannot strand an already-posted exact-head verdict."""
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    if bash is None or jq is None:
        pytest.skip("bash and jq are required")
    calls = tmp_path / "wake-calls"
    attempts = tmp_path / "wake-attempts"
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nprintf '%s\\n' \"$*\" >>\"$CALLS\"\n"
        "if [[ \"$*\" == \"api repos/ContextualWisdomLab/example/actions/runs/42\" ]]; then n=0; [[ -f \"$ATTEMPTS\" ]] && n=$(cat \"$ATTEMPTS\"); n=$((n+1)); printf '%s' \"$n\" >\"$ATTEMPTS\"; if [[ \"$n\" -eq 1 ]]; then exit 75; fi; printf '%s\\n' \"$RUN_JSON\"; exit 0; fi\n"
        "if [[ \"$*\" == \"api -X POST repos/ContextualWisdomLab/example/actions/runs/42/rerun-failed-jobs\" ]]; then exit 0; fi\nexit 97\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    fake_timeout = tmp_path / "timeout"
    fake_timeout.write_text("#!/usr/bin/env bash\nset -euo pipefail\nshift\nexec \"$@\"\n", encoding="utf-8")
    fake_timeout.chmod(0o755)
    fake_sleep = tmp_path / "sleep"
    fake_sleep.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_sleep.chmod(0o755)
    run_json = {"id": 42, "event": "pull_request_target", "path": ".github/workflows/opencode-review.yml", "pull_requests": [{"number": 1437, "head": {"sha": HEAD_SHA}}], "status": "completed", "conclusion": "failure"}
    result = subprocess.run(
        [bash, "-c", _wake_script()],
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}", "CALLS": str(calls), "ATTEMPTS": str(attempts), "RUN_JSON": json.dumps(run_json), "GH_TOKEN": "test-token", "GH_REPOSITORY": "ContextualWisdomLab/example", "PR_NUMBER": "1437", "PR_HEAD_SHA": HEAD_SHA, "REQUIRED_RUN_ID": "42", "WAKE_TOKEN_SOURCE": "github-token"},
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Exact required-run lookup attempt 1/12 failed" in result.stdout
    assert "Re-ran failed jobs for exact-PR/head Required OpenCode Review run 42." in result.stdout
    assert calls.read_text(encoding="utf-8").splitlines() == ["api repos/ContextualWisdomLab/example/actions/runs/42", "api repos/ContextualWisdomLab/example/actions/runs/42", "api -X POST repos/ContextualWisdomLab/example/actions/runs/42/rerun-failed-jobs"]
''', encoding="utf-8")

SELF.write_text(r'''"""Regression contract for one-shot Required OpenCode verdict admission."""
from pathlib import Path
WORKFLOW = Path(".github/workflows/opencode-review.yml")

def _step() -> str:
    """Return only the one-shot verdict-admission step."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    return workflow.split("      - name: Fail closed without a current-head OpenCode verdict\n", 1)[1].split("\n  cancel-superseded-opencode-review-runs:\n", 1)[0]

def test_one_shot_revalidates_live_state_before_reviews() -> None:
    """Current authority is established before formal review evidence is read."""
    step = _step()
    live = 'timeout 30s gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}"'
    reviews = 'timeout 30s gh api --paginate "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews?per_page=100"'
    assert live in step and reviews in step and step.index(live) < step.index(reviews)

def test_transport_reads_are_bounded_but_model_wait_is_not() -> None:
    """GitHub transport gets a bound; semantic model reasoning gets no deadline."""
    step = _step()
    assert step.count("timeout 30s gh api") == 2
    for token in ("while :; do", "poll_interval_seconds", "poll_deadline_epoch", "max_poll_transport_failures", "sleep "):
        assert token not in step
''', encoding="utf-8")

regression = REGRESSION.read_text(encoding="utf-8")
regression = regression.replace('    return textwrap.dedent(step.split("        run: |\\n", 1)[1])\n', '    block = step.split("        run: |\\n", 1)[1].split("\\n  cancel-superseded-opencode-review-runs:\\n", 1)[0]\n    return textwrap.dedent(block)\n', 1)
regression = regression.replace('    assert "select(.head_sha == $head)" in dispatched\n', '    assert "pull_requests // []" in dispatched\n    assert "(.number // 0) | tostring" in dispatched\n    assert "select(.head_sha == $head)" not in dispatched\n', 1)
old_selector = '''def wake_selector(run: dict[str, object], *, head: str = HEAD, run_id: int = 42) -> str:
    """Execute the wake step's run-validation jq program in isolation."""
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is required to execute the production wake selector")
    dispatched = DISPATCH_WORKFLOW.read_text(encoding="utf-8")
    marker = """jq -r --arg head "$PR_HEAD_SHA" --argjson run_id "$REQUIRED_RUN_ID" '"""
    start = dispatched.index(marker) + len(marker)
    end = dispatched.index("\\n            ')", start)
    result = subprocess.run(
        [jq, "-r", "--arg", "head", head, "--argjson", "run_id", str(run_id), dispatched[start:end]],
        input=json.dumps(run),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()
'''
new_selector = '''def wake_selector(run: dict[str, object], *, head: str = HEAD, pr: int = 1437, run_id: int = 42) -> str:
    """Execute the wake step's exact run/PR/head validation jq program."""
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is required to execute the production wake selector")
    dispatched = DISPATCH_WORKFLOW.read_text(encoding="utf-8")
    marker = """jq -r --arg head "$PR_HEAD_SHA" --arg pr "$PR_NUMBER" --argjson run_id "$REQUIRED_RUN_ID" '"""
    start = dispatched.index(marker) + len(marker)
    end = dispatched.index("\\n            ')", start)
    result = subprocess.run(
        [jq, "-r", "--arg", "head", head, "--arg", "pr", str(pr), "--argjson", "run_id", str(run_id), dispatched[start:end]],
        input=json.dumps(run), text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()
'''
regression = replace_once(regression, old_selector, new_selector, "wake selector fixture")
old_fixture = '''def required_run(*, run_id: int = 42, head_sha: str = HEAD, path: str = ".github/workflows/opencode-review.yml") -> dict[str, object]:
    """Build one realistic single-run GET REST API record.

    Mirrors the real shape a sibling repo sees for a run injected by the org's
    required-workflow ruleset (this repo's actual central-hub use case): `name`
    is the bare workflow name and `display_title` is a plain PR title, with no
    PR number or head SHA embedded in either -- unlike a native same-repo
    trigger, where both fields carry the rendered `run-name`.
    """
    return {
        "id": run_id,
        "head_sha": head_sha,
        "event": "pull_request_target",
        "name": "Required OpenCode Review",
        "display_title": "Fix an unrelated example bug",
        "path": path,
        "workflow_url": (
            "https://api.github.com/repos/ContextualWisdomLab/example"
            "/actions/required_workflows/9"
        ),
        "status": "completed",
        "conclusion": "failure",
    }
'''
new_fixture = '''def required_run(*, run_id: int = 42, pr_head_sha: str = HEAD, pr_number: int = 1437, path: str = ".github/workflows/opencode-review.yml") -> dict[str, object]:
    """Build a pull_request_target run whose top-level head_sha is the base SHA."""
    return {
        "id": run_id,
        "head_sha": "f" * 40,
        "event": "pull_request_target",
        "name": "Required OpenCode Review",
        "display_title": "Fix an unrelated example bug",
        "path": path,
        "workflow_url": "https://api.github.com/repos/ContextualWisdomLab/example/actions/required_workflows/9",
        "pull_requests": [{"number": pr_number, "head": {"sha": pr_head_sha}}],
        "status": "completed",
        "conclusion": "failure",
    }
'''
regression = replace_once(regression, old_fixture, new_fixture, "pull_request_target run fixture")
regression = regression.replace('required_run(head_sha="b" * 40)', 'required_run(pr_head_sha="b" * 40)', 1)
wrong_workflow = 'def test_wake_selector_rejects_a_referenced_run_for_a_different_workflow() -> None:\n'
if 'def test_wake_selector_rejects_a_referenced_run_for_a_different_pr()' not in regression:
    regression = replace_once(regression, wrong_workflow, 'def test_wake_selector_rejects_a_referenced_run_for_a_different_pr() -> None:\n    """A run id for another PR cannot receive the wake mutation."""\n    assert wake_selector(required_run(pr_number=9999)) == ""\n\n\n' + wrong_workflow, "wrong PR wake regression")
regression = replace_once(regression, '            "PR_HEAD_SHA": HEAD,\n            "REQUIRED_RUN_ID": "42",\n', '            "PR_NUMBER": "1437",\n            "PR_HEAD_SHA": HEAD,\n            "REQUIRED_RUN_ID": "42",\n', "formal wake PR identity fixture")
REGRESSION.write_text(regression, encoding="utf-8")

live_draft = LIVE_DRAFT.read_text(encoding="utf-8").replace("Reviews API read failed 3 consecutive times", "Reviews API read failed during one-shot current-head verdict admission")
LIVE_DRAFT.write_text(live_draft, encoding="utf-8")

architecture = ARCHITECTURE.read_text(encoding="utf-8")
if "### Required OpenCode one-shot verdict admission" not in architecture:
    ARCHITECTURE.write_text(architecture + "\n\n### Required OpenCode one-shot verdict admission\n\nThe protected required workflow validates live PR state once, reads formal review evidence once, and releases its runner immediately when no exact-head verdict exists. The authenticated default-branch dispatch revalidates repository, immutable run id, workflow path, PR number, and `pull_requests[].head.sha` before `rerun-failed-jobs`. A bounded retry absorbs transient GitHub run-lookup failures; model reasoning itself has no caller wall-clock deadline.\n", encoding="utf-8")

doctoring = DOCTORING.read_text(encoding="utf-8")
if "### Exact-run wake identity and transient lookup correction" not in doctoring:
    DOCTORING.write_text(doctoring + "\n\n### Exact-run wake identity and transient lookup correction\n\nFor `pull_request_target`, top-level workflow-run `head_sha` identifies the base revision, not the PR head. Wake authority binds immutable run id, event, workflow path, exact PR number, and `pull_requests[].head.sha`. Transient run-lookup failures are retried within a bounded transport loop so a posted formal verdict cannot be stranded by one GitHub API timeout.\n", encoding="utf-8")

changelog = CHANGELOG.read_text(encoding="utf-8")
note = "- Required OpenCode Review now releases its runner after one exact-head verdict admission read; exact-run wake binds PR number plus `pull_requests[].head.sha` and tolerates bounded transient GitHub run-lookup failures without imposing a model reasoning timeout.\n"
if note not in changelog:
    CHANGELOG.write_text(note + changelog, encoding="utf-8")
