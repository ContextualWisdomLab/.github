"""Executable regressions for live-authoritative Strix repository_dispatch admission."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "strix.yml"


def _workflow() -> dict[str, object]:
    """Load the production Strix workflow for cross-job contract checks."""
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _steps() -> list[dict[str, object]]:
    """Return the ordered steps of the authoritative Strix scan job."""
    return _workflow()["jobs"]["strix"]["steps"]


def _step(name: str) -> dict[str, object]:
    """Return a named step from the authoritative Strix scan job."""
    return next(step for step in _steps() if step.get("name") == name)


def _step_index(name: str) -> int:
    """Return the position of a named step in the authoritative Strix scan job."""
    return next(index for index, step in enumerate(_steps()) if step.get("name") == name)


def _fake_gh_environment(tmp_path: Path, pull_request: dict[str, object] | None, *, gh_fails: bool) -> dict[str, str]:
    """Build a deterministic fake-GitHub shell environment for workflow-step tests."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [ \"${FAKE_GH_FAIL:-0}\" = 1 ]; then exit 1; fi\n"
        "printf '%s\\n' \"${FAKE_PR_JSON:?}\"\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    output_path = tmp_path / "github-output"
    output_path.write_text("", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "GITHUB_OUTPUT": str(output_path),
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_SERVER_URL": "https://github.com",
            "FAKE_PR_JSON": json.dumps(pull_request or {}),
            "FAKE_GH_FAIL": "1" if gh_fails else "0",
        }
    )
    return env


def _run_preflight(tmp_path: Path, pull_request: dict[str, object] | None, *, gh_fails: bool = False) -> tuple[int, str]:
    """Execute the production dispatch admission shell through its live-state decision."""
    validation = _step("Validate repository dispatch against live pull request metadata")
    script = str(validation["run"])
    # Exercise the exact validation program, but stop before the open/current
    # case performs the subsequent trusted git materialization.
    script = script.split('trusted_workspace="$RUNNER_TEMP/trusted-workspace"', 1)[0]

    env = _fake_gh_environment(tmp_path, pull_request, gh_fails=gh_fails)
    env.update(
        {
            "REPOSITORY": "ContextualWisdomLab/example",
            "PR_NUMBER": "42",
            "SUPPLIED_BASE_REF": "main",
            "SUPPLIED_BASE_SHA": "a" * 40,
            "SUPPLIED_HEAD_SHA": "b" * 40,
        }
    )
    result = subprocess.run(["bash", "-c", script], env=env, text=True, capture_output=True)
    return result.returncode, Path(env["GITHUB_OUTPUT"]).read_text(encoding="utf-8")


def _run_status_revalidation(
    tmp_path: Path,
    pull_request: dict[str, object] | None,
    *,
    gh_fails: bool = False,
) -> tuple[int, str]:
    """Execute the late status-publication live-state gate against fake GitHub state."""
    validation = _step("Revalidate repository dispatch before status publication")
    script = str(validation["run"])
    env = _fake_gh_environment(tmp_path, pull_request, gh_fails=gh_fails)
    env.update(
        {
            "REPOSITORY": "ContextualWisdomLab/example",
            "PR_NUMBER": "42",
            "EXPECTED_HEAD_SHA": "b" * 40,
        }
    )
    result = subprocess.run(["bash", "-c", script], env=env, text=True, capture_output=True)
    return result.returncode, Path(env["GITHUB_OUTPUT"]).read_text(encoding="utf-8")


def _live_pr(*, state: str = "open", draft: bool = False, head: str | None = None, base: str | None = None) -> dict[str, object]:
    """Build canonical live pull-request JSON for exact-head admission tests."""
    return {
        "state": state,
        "draft": draft,
        "base": {
            "repo": {"full_name": "ContextualWisdomLab/example"},
            "ref": "main",
            "sha": base or "a" * 40,
        },
        "head": {
            "repo": {"full_name": "ContextualWisdomLab/example"},
            "sha": head or "b" * 40,
        },
    }


def test_repository_dispatch_revalidates_live_state_and_head_before_scan(tmp_path: Path) -> None:
    """Initial dispatch admission distinguishes resolved/draft targets from stale heads."""
    validation = _step("Validate repository dispatch against live pull request metadata")
    assert validation.get("id") == "dispatch_validation"
    script = str(validation["run"])
    assert "live_draft=" in script
    assert "should_scan=false" in script
    assert "should_scan=true" in script

    rc, output = _run_preflight(tmp_path / "ready", _live_pr())
    assert rc == 0
    assert "should_scan=true" in output

    # A completed PR on the exact dispatched head is resolved work, not stale
    # evidence. Its base may already have advanced after merge; no scan/status
    # publication may occur after live closure.
    rc, output = _run_preflight(
        tmp_path / "closed",
        _live_pr(state="closed", base="c" * 40),
    )
    assert rc == 0
    assert "should_scan=false" in output

    # Symmetric stale-event ordering: a ready dispatch that starts after the PR
    # became draft must use the live draft state and perform no admission work.
    rc, output = _run_preflight(tmp_path / "draft", _live_pr(draft=True))
    assert rc == 0
    assert "should_scan=false" in output

    rc, _ = _run_preflight(tmp_path / "stale", _live_pr(head="d" * 40))
    assert rc != 0

    rc, _ = _run_preflight(tmp_path / "lookup", None, gh_fails=True)
    assert rc != 0


def test_repository_dispatch_skip_signal_guards_every_downstream_admission_effect() -> None:
    """Resolved/draft dispatches require explicit true authority before early scan work."""
    guarded_names = {
        "Resolve target repository visibility",
        "Fetch pull request head for trusted scan",
        "Self-test Strix required workflow contract",
        "Gate Strix secrets",
    }
    for name in guarded_names:
        condition = str(_step(name).get("if", ""))
        assert "steps.dispatch_validation.outputs.should_scan == 'true'" in condition, name

    # Status publication intentionally uses a second, later live-state authority
    # because a PR can close, become draft, or move heads while a long scan runs.
    publish_condition = str(_step("Publish same-head manual Strix status").get("if", ""))
    assert "steps.dispatch_publish_validation.outputs.publish_status == 'true'" in publish_condition


def test_repository_dispatch_revalidates_live_state_again_before_status_publication(tmp_path: Path) -> None:
    """Hours-long scans cannot publish after the exact target closes or becomes draft."""
    refresh_name = "Refresh OpenCode app token for Strix status revalidation"
    validation_name = "Revalidate repository dispatch before status publication"
    assert _step_index(refresh_name) < _step_index(validation_name)

    refresh = _step(refresh_name)
    validation = _step(validation_name)
    assert refresh.get("id") == "status_target_app_token"
    refresh_condition = str(refresh.get("if", ""))
    # Exact `true` is fail-closed: absent/malformed outputs must not be treated as
    # permission to refresh credentials or proceed toward status publication.
    assert "steps.dispatch_validation.outputs.should_scan == 'true'" in refresh_condition
    assert "github.event_name == 'repository_dispatch'" in refresh_condition

    assert validation.get("id") == "dispatch_publish_validation"
    token_expression = str(validation.get("env", {}).get("GH_TOKEN", ""))
    assert "status_target_app_token.outputs.token" in token_expression
    assert "target_app_token.outputs.token" not in token_expression

    rc, output = _run_status_revalidation(tmp_path / "ready", _live_pr())
    assert rc == 0
    assert "publish_status=true" in output

    rc, output = _run_status_revalidation(tmp_path / "closed", _live_pr(state="closed"))
    assert rc == 0
    assert "publish_status=false" in output

    rc, output = _run_status_revalidation(tmp_path / "draft", _live_pr(draft=True))
    assert rc == 0
    assert "publish_status=false" in output

    rc, _ = _run_status_revalidation(tmp_path / "stale", _live_pr(head="d" * 40))
    assert rc != 0

    rc, _ = _run_status_revalidation(tmp_path / "lookup", None, gh_fails=True)
    assert rc != 0


def test_repository_dispatch_skip_signal_crosses_the_status_job_boundary() -> None:
    """Both manual-status publishers require fresh late-bound live authority."""
    workflow = _workflow()
    scan_job = workflow["jobs"]["strix"]
    status_job = workflow["jobs"]["publish-manual-pr-evidence-status"]

    outputs = scan_job.get("outputs", {})
    assert outputs.get("should_scan") == "${{ steps.dispatch_validation.outputs.should_scan }}"
    assert outputs.get("publish_status") == "${{ steps.dispatch_publish_validation.outputs.publish_status }}"

    in_job_condition = str(_step("Publish same-head manual Strix status").get("if", ""))
    assert "steps.dispatch_publish_validation.outputs.publish_status == 'true'" in in_job_condition

    status_condition = str(status_job.get("if", ""))
    assert "needs.strix.outputs.should_scan == 'true'" in status_condition
    assert "needs.strix.outputs.publish_status == 'true'" in status_condition
    assert "github.event_name == 'repository_dispatch'" in status_condition
