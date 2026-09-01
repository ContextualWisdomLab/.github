"""Contracts for trusted CodeGraph evidence in the independent Noema reviewer."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from scripts.ci import noema_review_gate as gate


ROOT = Path(__file__).resolve().parents[1]
NOEMA_WORKFLOW = ROOT / ".github/workflows/noema-review.yml"
NOEMA_GATE = ROOT / "scripts/ci/noema_review_gate.py"
TOKEN_LOADER = ROOT / "scripts/ci/load_contextual_orchestrator_token.sh"
CODEGRAPH_HELPER = ROOT / "scripts/ci/noema_codegraph_context.sh"


def test_noema_workflow_materializes_trusted_codegraph_before_review() -> None:
    """The production review step must source the materializing loader before model work."""
    workflow = NOEMA_WORKFLOW.read_text(encoding="utf-8")
    review_step = workflow.split("- name: Run Noema LLM review and submit verdict", 1)[1]
    loader = 'source "$GITHUB_WORKSPACE/scripts/ci/load_contextual_orchestrator_token.sh"'
    review = "python3 -m scripts.ci.noema_review_gate"
    assert review_step.index(loader) < review_step.index(review)
    assert "NOEMA_REVIEW_TOKEN_SOURCE:" in review_step

    loader_source = TOKEN_LOADER.read_text(encoding="utf-8")
    assert "scripts/ci/noema_codegraph_context.sh" in loader_source
    assert "NOEMA_CODEGRAPH_CONTEXT_PATH" in loader_source
    assert "NOEMA_REQUIRE_CODEGRAPH_CONTEXT=1" in loader_source


def test_noema_codegraph_helper_is_real_shell_and_keeps_pr_source_data_only() -> None:
    """CodeGraph may parse exact-head source but must not execute target-owned tooling."""
    helper_bytes = CODEGRAPH_HELPER.read_bytes()
    assert helper_bytes.startswith(b"#!/usr/bin/env bash\n")
    subprocess.run(
        ["bash", "-n", str(CODEGRAPH_HELPER)],
        check=True,
        capture_output=True,
        text=True,
    )

    helper = helper_bytes.decode("utf-8")
    for required in (
        "CODEGRAPH_NO_DOWNLOAD=1",
        "refs/pull/${PR_NUMBER}/head",
        "EXPECTED_HEAD_SHA",
        "PR_BASE_SHA",
        "unset GH_TOKEN",
        "codegraph-package/package-lock.json",
        "codegraph-package/package.json",
        '"$CODEGRAPH_BIN" init -i',
        '"$CODEGRAPH_BIN" explore',
        "# Trusted CodeGraph current-head evidence",
        "Head SHA:",
    ):
        assert required in helper
    for forbidden in (
        "pytest",
        "npm test",
        "npm run",
        "cargo test",
        "go test",
        "gradle",
        "mvn test",
    ):
        assert forbidden not in helper


def _write_executable(path: Path, body: str) -> None:
    """Write one executable shell fixture without depending on repository tooling."""
    path.write_text(body, encoding="utf-8")
    path.chmod(0o700)


def _loader_environment(tmp_path: Path, *, observed_head: str) -> tuple[dict[str, str], Path]:
    """Build an isolated Noema loader environment with deterministic GitHub stubs."""
    expected_head = "a" * 40
    base_sha = "b" * 40
    runner_temp = tmp_path / "runner"
    workspace = tmp_path / "workspace"
    bin_dir = tmp_path / "bin"
    helper_dir = workspace / "scripts" / "ci"
    runner_temp.mkdir()
    helper_dir.mkdir(parents=True)
    bin_dir.mkdir()

    token_file = tmp_path / "sidecar-token"
    token_file.write_text("sidecar-secret", encoding="utf-8")
    token_file.chmod(0o600)

    _write_executable(
        bin_dir / "gh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"printf '%s\\n' '{{\"head\":{{\"sha\":\"{observed_head}\"}},\"base\":{{\"sha\":\"{base_sha}\"}}}}'\n",
    )
    _write_executable(
        bin_dir / "jq",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "query=\"${@: -1}\"\n"
        "case \"$query\" in\n"
        f"  *head.sha*) printf '%s\\n' '{observed_head}' ;;\n"
        f"  *base.sha*) printf '%s\\n' '{base_sha}' ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n",
    )
    _write_executable(
        helper_dir / "noema_codegraph_context.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '# Trusted CodeGraph current-head evidence\\n\\n- Head SHA: `%s`\\n- Base SHA: `%s`\\n' \"$EXPECTED_HEAD_SHA\" \"$PR_BASE_SHA\" >\"$NOEMA_CODEGRAPH_CONTEXT_PATH\"\n"
        "printf '%s' \"$PR_BASE_SHA\" >\"$RUNNER_TEMP/base-seen\"\n",
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE": str(token_file),
            "NOEMA_REVIEW_TOKEN_SOURCE": "noema-review-pat",
            "TARGET_REPOSITORY": "ContextualWisdomLab/example",
            "PR_NUMBER": "7",
            "EXPECTED_HEAD_SHA": expected_head,
            "GH_TOKEN": "review-token",
            "RUNNER_TEMP": str(runner_temp),
            "GITHUB_WORKSPACE": str(workspace),
        }
    )
    return env, runner_temp


def test_token_loader_materializes_codegraph_for_the_same_live_head(tmp_path: Path) -> None:
    """The sourced production seam must bind base/head identity and publish required context."""
    env, runner_temp = _loader_environment(tmp_path, observed_head="a" * 40)
    command = (
        "set -euo pipefail; "
        f"source {TOKEN_LOADER!s}; "
        'test "$NOEMA_REQUIRE_CODEGRAPH_CONTEXT" = 1; '
        'test "$NOEMA_CODEGRAPH_CONTEXT_PATH" = "$RUNNER_TEMP/noema-codegraph-evidence.md"; '
        'test -s "$NOEMA_CODEGRAPH_CONTEXT_PATH"'
    )
    subprocess.run(
        ["bash", "-c", command],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert (runner_temp / "base-seen").read_text(encoding="utf-8") == "b" * 40


def test_token_loader_refuses_head_change_before_codegraph_materialization(tmp_path: Path) -> None:
    """A changing PR head cannot reuse the trigger identity to mint structural evidence."""
    env, runner_temp = _loader_environment(tmp_path, observed_head="c" * 40)
    result = subprocess.run(
        ["bash", "-c", f"set -euo pipefail; source {TOKEN_LOADER!s}"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "refused stale or malformed pull-request source identity" in result.stderr
    assert not (runner_temp / "base-seen").exists()


def test_noema_gate_requires_exact_head_bound_codegraph_when_workflow_requests_it() -> None:
    """The model gate must fail closed if required structural evidence is absent or stale."""
    source = NOEMA_GATE.read_text(encoding="utf-8")
    core_source = (ROOT / "scripts/ci/_noema_review_core.py").read_text(encoding="utf-8")
    assert "NOEMA_REQUIRE_CODEGRAPH_CONTEXT" in core_source
    assert "NOEMA_CODEGRAPH_CONTEXT_PATH" in core_source
    assert "Trusted CodeGraph current-head evidence" in core_source
    assert "CodeGraph context head does not match the pull request head" in core_source
    assert "strict public entrypoint" in source.lower()


def test_codegraph_loader_accepts_only_the_exact_reviewed_head(monkeypatch, tmp_path: Path) -> None:
    """Exact-head packets are admitted while predecessor packets are rejected."""
    current_head = "a" * 40
    packet = tmp_path / "codegraph.md"
    packet.write_text(
        "# Trusted CodeGraph current-head evidence\n\n"
        f"- Head SHA: `{current_head}`\n\n"
        "## Changed-scope exploration\nsource-backed graph evidence\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NOEMA_REQUIRE_CODEGRAPH_CONTEXT", "1")
    monkeypatch.setenv("NOEMA_CODEGRAPH_CONTEXT_PATH", str(packet))
    assert "source-backed graph evidence" in gate.load_codegraph_context(current_head)
    with pytest.raises(RuntimeError, match="head does not match"):
        gate.load_codegraph_context("b" * 40)


def test_codegraph_loader_fails_closed_when_required_packet_is_missing(monkeypatch) -> None:
    """Required structural context cannot silently degrade to changed-file context only."""
    monkeypatch.setenv("NOEMA_REQUIRE_CODEGRAPH_CONTEXT", "1")
    monkeypatch.delenv("NOEMA_CODEGRAPH_CONTEXT_PATH", raising=False)
    with pytest.raises(RuntimeError, match="path was not configured"):
        gate.load_codegraph_context("a" * 40)
