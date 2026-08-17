"""Injected-allowlist regression for exact ContextualWisdomLab/Orgmetra dispatch."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from scripts.ci.agent_mention_router import eligible_agents, parse_event, parse_repository_allowlist


REPO_ROOT = Path(__file__).resolve().parents[1]
ORGMETRA = "ContextualWisdomLab/Orgmetra"
ORGMETRA_26_HEAD = "5c5fb1e548c69c1186e8ddb9ccbf439874b78985"
ORGMETRA_26_BASE_REF = "develop"
ORGMETRA_26_BASE_SHA = "0f1b5fcb0123456789abcdef0123456789abcdef"
ORGMETRA_26_HEAD_REF = "cursor/orgmetra-review-26"
INJECTED_ALLOWLIST = (
    "ContextualWisdomLab/.github,ContextualWisdomLab/naruon,"
    f"{ORGMETRA},ContextualWisdomLab/kaefa"
)
SHARED_WORKFLOWS = (
    ".github/workflows/opencode-review-dispatch.yml",
    ".github/workflows/pr-review-merge-scheduler.yml",
    ".github/workflows/pr-review-fix-scheduler.yml",
    ".github/workflows/agent-mention-router.yml",
    ".github/workflows/opencode-review.yml",
    ".github/workflows/noema-review.yml",
)


def _extract_run_block(workflow_text: str, step_name: str) -> str:
    """Return the bash body of one named workflow step."""
    lines = workflow_text.splitlines()
    step_index = next(
        index for index, line in enumerate(lines) if line.strip() == f"- name: {step_name}"
    )
    run_index = next(
        index
        for index in range(step_index + 1, len(lines))
        if lines[index].strip() == "run: |"
    )
    run_indent = len(lines[run_index]) - len(lines[run_index].lstrip())
    block_lines = []
    for line in lines[run_index + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= run_indent:
            break
        block_lines.append(line[run_indent + 2 :] if len(line) >= run_indent + 2 else "")
    return "\n".join(block_lines) + "\n"


def orgmetra_pr26_json(
    *,
    state: str = "open",
    base_ref: str = ORGMETRA_26_BASE_REF,
    base_sha: str = ORGMETRA_26_BASE_SHA,
    head_ref: str = ORGMETRA_26_HEAD_REF,
    head_sha: str = ORGMETRA_26_HEAD,
    base_repo: str = ORGMETRA,
    head_repo: str = ORGMETRA,
) -> str:
    """Return live PR JSON for the Orgmetra #26 fixture."""
    return json.dumps(
        {
            "number": 26,
            "state": state,
            "base": {
                "ref": base_ref,
                "sha": base_sha,
                "repo": {"full_name": base_repo, "private": False},
            },
            "head": {
                "ref": head_ref,
                "sha": head_sha,
                "repo": {"full_name": head_repo},
            },
        }
    )


def _write_fake_gh(tmp_path: Path, payload: str) -> Path:
    """Install a PATH-first gh that returns one PR JSON payload."""
    fake = tmp_path / "gh"
    fake.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        'if [ "${1:-}" = "api" ]; then\n'
        f"  cat <<'EOF'\n{payload}\nEOF\n"
        "  exit 0\n"
        "fi\n"
        'echo "unexpected gh $*" >&2\n'
        "exit 1\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return fake


def _dispatch_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    """Build the validate-step environment for an injected Orgmetra allowlist."""
    env = {
        **os.environ,
        "EVENT_NAME": "repository_dispatch",
        "DISPATCH_ACTOR": "github-actions[bot]",
        "DISPATCH_SENDER": "github-actions[bot]",
        "ALLOWED_DISPATCH_ACTOR": "github-actions[bot]",
        "ALLOWED_DISPATCH_TARGETS": INJECTED_ALLOWLIST,
        "TARGET_REPOSITORY": ORGMETRA,
        "PR_NUMBER": "26",
        "SUPPLIED_BASE_REF": ORGMETRA_26_BASE_REF,
        "SUPPLIED_BASE_SHA": ORGMETRA_26_BASE_SHA,
        "SUPPLIED_HEAD_REF": ORGMETRA_26_HEAD_REF,
        "SUPPLIED_HEAD_SHA": ORGMETRA_26_HEAD,
        "GITHUB_OUTPUT": str(tmp_path / "github-output"),
        "PATH": f"{tmp_path}:{os.environ.get('PATH', '')}",
    }
    env.update(overrides)
    return env


def test_shared_dispatch_surfaces_do_not_hardcode_orgmetra() -> None:
    """The inventory lives only in OPENCODE_REPOSITORY_DISPATCH_TARGETS."""
    for relative in SHARED_WORKFLOWS:
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "ContextualWisdomLab/Orgmetra" not in text, relative
        if relative.endswith(("noema-review.yml", "opencode-review.yml")):
            continue
        assert "vars.OPENCODE_REPOSITORY_DISPATCH_TARGETS" in text, relative


def test_opencode_repository_dispatch_allows_orgmetra_pr26_exact_head_and_rejects_non_cwl_or_typo_targets(
    tmp_path: Path,
) -> None:
    """Exact Orgmetra #26 head/base pass only when the injected allowlist names it."""
    workflow = (REPO_ROOT / ".github/workflows/opencode-review-dispatch.yml").read_text(
        encoding="utf-8"
    )
    shell = _extract_run_block(
        workflow, "Bind workflow inputs to live organization pull request metadata"
    )
    _write_fake_gh(tmp_path, orgmetra_pr26_json())

    accepted = subprocess.run(
        ["bash", "-c", shell],
        env=_dispatch_env(tmp_path),
        text=True,
        capture_output=True,
        check=False,
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert f"Authorized repository_dispatch actor=" in accepted.stdout
    assert f"target={ORGMETRA}" in accepted.stdout
    assert f"Validated current live metadata for {ORGMETRA}#26" in accepted.stdout
    assert ORGMETRA_26_HEAD in accepted.stdout
    output = Path(_dispatch_env(tmp_path)["GITHUB_OUTPUT"]).read_text(encoding="utf-8")
    assert f"target_repository={ORGMETRA}" in output
    assert f"head_sha={ORGMETRA_26_HEAD}" in output
    assert f"base_ref={ORGMETRA_26_BASE_REF}" in output

    cases = (
        ({"TARGET_REPOSITORY": "OtherOrg/Orgmetra"}, "rejected target=OtherOrg/Orgmetra"),
        (
            {"TARGET_REPOSITORY": "ContextualWisdomLab/Orgmetrra"},
            "rejected target=ContextualWisdomLab/Orgmetrra",
        ),
        ({"TARGET_REPOSITORY": ""}, "rejected target="),
        (
            {"SUPPLIED_HEAD_SHA": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"},
            "does not match the live pull request",
        ),
        (
            {"SUPPLIED_BASE_SHA": "cafebabecafebabecafebabecafebabecafebabe"},
            "does not match the live pull request",
        ),
        (
            {"ALLOWED_DISPATCH_TARGETS": "ContextualWisdomLab/.github,ContextualWisdomLab/naruon"},
            f"rejected target={ORGMETRA}",
        ),
    )
    for overrides, expected in cases:
        rejected = subprocess.run(
            ["bash", "-c", shell],
            env=_dispatch_env(tmp_path, **overrides),
            text=True,
            capture_output=True,
            check=False,
        )
        assert rejected.returncode == 1, overrides
        assert expected in rejected.stdout + rejected.stderr

    _write_fake_gh(tmp_path, orgmetra_pr26_json(state="closed"))
    closed = subprocess.run(
        ["bash", "-c", shell],
        env=_dispatch_env(tmp_path),
        text=True,
        capture_output=True,
        check=False,
    )
    assert closed.returncode == 1
    assert "rejected closed" in closed.stdout

    _write_fake_gh(
        tmp_path,
        orgmetra_pr26_json(),
    )
    regex_rejected = subprocess.run(
        ["bash", "-c", shell],
        env=_dispatch_env(
            tmp_path,
            TARGET_REPOSITORY="OtherOrg/Orgmetra",
            ALLOWED_DISPATCH_TARGETS=f"{INJECTED_ALLOWLIST},OtherOrg/Orgmetra",
        ),
        text=True,
        capture_output=True,
        check=False,
    )
    assert regex_rejected.returncode == 1
    assert "outside ContextualWisdomLab" in regex_rejected.stdout


def test_merge_and_fix_schedulers_accept_injected_orgmetra(tmp_path: Path) -> None:
    """Shared scheduler allowlists accept exact Orgmetra when the variable includes it."""
    merge = (REPO_ROOT / ".github/workflows/pr-review-merge-scheduler.yml").read_text(
        encoding="utf-8"
    )
    merge_shell = _extract_run_block(merge, "Validate targeted repository dispatch")
    _write_fake_gh(tmp_path, orgmetra_pr26_json())
    merge_output = tmp_path / "merge-output"
    merge_env = {
        **os.environ,
        "GITHUB_EVENT_NAME": "repository_dispatch",
        "GITHUB_REPOSITORY": "ContextualWisdomLab/.github",
        "DEFAULT_BRANCH": "main",
        "TARGET_REPOSITORY_INPUT": ORGMETRA,
        "TARGET_PR_NUMBER": "26",
        "TARGET_BASE_BRANCH_INPUT": ORGMETRA_26_BASE_REF,
        "ALLOWED_TARGET_REPOSITORIES": INJECTED_ALLOWLIST,
        "GITHUB_OUTPUT": str(merge_output),
        "PATH": f"{tmp_path}:{os.environ.get('PATH', '')}",
    }
    accepted = subprocess.run(
        ["bash", "-c", merge_shell],
        env=merge_env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert ORGMETRA in merge_output.read_text(encoding="utf-8")

    typo = subprocess.run(
        ["bash", "-c", merge_shell],
        env={**merge_env, "TARGET_REPOSITORY_INPUT": "ContextualWisdomLab/Orgmetrra"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert typo.returncode == 1
    assert "absent from the configured exact allowlist" in typo.stdout

    fix = (REPO_ROOT / ".github/workflows/pr-review-fix-scheduler.yml").read_text(
        encoding="utf-8"
    )
    fix_shell = _extract_run_block(fix, "Validate scheduler target and dispatch authority")
    fix_env = {
        **os.environ,
        "EVENT_NAME": "repository_dispatch",
        "DISPATCH_ACTOR": "github-actions[bot]",
        "DISPATCH_SENDER": "github-actions[bot]",
        "ALLOWED_DISPATCH_ACTOR": "github-actions[bot]",
        "ALLOWED_TARGET_REPOSITORIES": INJECTED_ALLOWLIST,
        "TARGET_REPOSITORY": ORGMETRA,
    }
    assert (
        subprocess.run(
            ["bash", "-c", fix_shell],
            env=fix_env,
            text=True,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )
    assert (
        subprocess.run(
            ["bash", "-c", fix_shell],
            env={**fix_env, "TARGET_REPOSITORY": "OtherOrg/Orgmetra"},
            text=True,
            capture_output=True,
            check=False,
        ).returncode
        == 1
    )


def test_router_and_sweep_accept_injected_orgmetra_allowlist() -> None:
    """Router/sweep treat Orgmetra as dispatchable only from the injected variable."""
    allowlist = parse_repository_allowlist(INJECTED_ALLOWLIST)
    assert ORGMETRA in allowlist
    with pytest.raises(ValueError, match="invalid repository"):
        parse_repository_allowlist("OtherOrg/Orgmetra")
    event = {
        "repository": {"full_name": ORGMETRA},
        "issue": {
            "number": 26,
            "pull_request": {"url": "https://api.github.test/pr/26"},
        },
        "comment": {
            "id": 91,
            "body": "@opencode-agent",
            "author_association": "MEMBER",
            "user": {"login": "maintainer", "type": "User"},
        },
        "pull_request": {
            "state": "open",
            "head": {"sha": ORGMETRA_26_HEAD, "ref": ORGMETRA_26_HEAD_REF},
            "base": {"ref": ORGMETRA_26_BASE_REF, "sha": ORGMETRA_26_BASE_SHA},
        },
    }
    request = parse_event(event)
    assert request is not None
    assert eligible_agents(request, opencode_allowlist=allowlist) == (
        ("opencode-agent",),
        (),
    )
    assert eligible_agents(request, opencode_allowlist=frozenset()) == (
        (),
        ("opencode-agent",),
    )
