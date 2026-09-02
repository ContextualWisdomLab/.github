"""Executable regressions for live-authoritative Strix repository_dispatch admission."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "strix.yml"


def _steps() -> list[dict[str, object]]:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    return workflow["jobs"]["strix"]["steps"]


def _step(name: str) -> dict[str, object]:
    return next(step for step in _steps() if step.get("name") == name)


def _run_preflight(tmp_path: Path, pull_request: dict[str, object] | None, *, gh_fails: bool = False) -> tuple[int, str]:
    validation = _step("Validate repository dispatch against live pull request metadata")
    script = str(validation["run"])
    # Exercise the exact validation program, but stop before the open/current
    # case performs the subsequent trusted git materialization.
    script = script.split('trusted_workspace="$RUNNER_TEMP/trusted-workspace"', 1)[0]

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
            "REPOSITORY": "ContextualWisdomLab/example",
            "PR_NUMBER": "42",
            "SUPPLIED_BASE_REF": "main",
            "SUPPLIED_BASE_SHA": "a" * 40,
            "SUPPLIED_HEAD_SHA": "b" * 40,
            "FAKE_PR_JSON": json.dumps(pull_request or {}),
            "FAKE_GH_FAIL": "1" if gh_fails else "0",
        }
    )
    result = subprocess.run(["bash", "-c", script], env=env, text=True, capture_output=True)
    return result.returncode, output_path.read_text(encoding="utf-8")


def _live_pr(*, state: str = "open", draft: bool = False, head: str | None = None, base: str | None = None) -> dict[str, object]:
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
    guarded_names = {
        "Fetch pull request head for trusted scan",
        "Self-test Strix required workflow contract",
        "Gate Strix secrets",
        "Publish same-head manual Strix status",
    }
    for name in guarded_names:
        condition = str(_step(name).get("if", ""))
        assert "steps.dispatch_validation.outputs.should_scan != 'false'" in condition, name
