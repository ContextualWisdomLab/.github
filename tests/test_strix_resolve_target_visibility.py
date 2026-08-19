"""Prove Strix visibility lookup retries flakes and stays fail-closed."""

from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci import strix_resolve_target_visibility as visibility


REPO_ROOT = Path(__file__).resolve().parents[1]
STRIX_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "strix.yml"
NOEMA_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "noema-review.yml"


def _workflow_step(workflow: str, name: str) -> str:
    """Return one named GitHub Actions step from a workflow document."""
    marker = f"      - name: {name}\n"
    if marker not in workflow:
        raise AssertionError(f"workflow step not found: {name}")
    start = workflow.index(marker)
    try:
        end = workflow.index("\n      - name:", start + len(marker))
    except ValueError:
        end = len(workflow)
    return workflow[start:end]


class _ScriptedGh:
    """Return scripted ``gh api`` outcomes in call order."""

    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[str] = []

    def __call__(self, repository: str) -> str:
        self.calls.append(repository)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return str(outcome)


def test_transient_visibility_api_failure_retries_then_succeeds() -> None:
    """A 502 then a boolean visibility must retry and continue the scan."""
    runner = _ScriptedGh(
        [
            visibility.VisibilityCommandError("gh: HTTP 502: Bad Gateway"),
            "true\n",
        ]
    )
    sleeps: list[float] = []

    assert (
        visibility.fetch_repository_visibility(
            "ContextualWisdomLab/aFIPC",
            run_gh=runner,
            sleep=sleeps.append,
        )
        == "true"
    )
    assert runner.calls == ["ContextualWisdomLab/aFIPC"] * 2
    assert sleeps == [1.0]


def test_empty_and_non_boolean_visibility_retries_then_succeeds() -> None:
    """Empty or non-boolean bodies are transient and must not abort the scan."""
    runner = _ScriptedGh(["", "null\n", "false"])
    sleeps: list[float] = []

    assert (
        visibility.fetch_repository_visibility(
            "ContextualWisdomLab/kaefa",
            run_gh=runner,
            sleep=sleeps.append,
        )
        == "false"
    )
    assert runner.calls == ["ContextualWisdomLab/kaefa"] * 3
    assert sleeps == [1.0, 2.0]


def test_timeout_visibility_lookup_retries_then_succeeds() -> None:
    """A GitHub API timeout is retried instead of failing the job in 1s."""
    runner = _ScriptedGh(
        [
            subprocess.TimeoutExpired(["gh", "api"], 20),
            "true",
        ]
    )
    sleeps: list[float] = []

    assert (
        visibility.fetch_repository_visibility(
            "ContextualWisdomLab/.github",
            run_gh=runner,
            sleep=sleeps.append,
        )
        == "true"
    )
    assert sleeps == [1.0]


def test_permanent_invalid_visibility_fails_closed() -> None:
    """Exhausted empty/non-boolean responses stay fail-closed."""
    runner = _ScriptedGh(["", "True", "1", "maybe"])
    sleeps: list[float] = []

    with pytest.raises(
        visibility.VisibilityResolutionError,
        match="did not resolve to true or false",
    ):
        visibility.fetch_repository_visibility(
            "ContextualWisdomLab/aFIPC",
            run_gh=runner,
            sleep=sleeps.append,
        )
    assert runner.calls == ["ContextualWisdomLab/aFIPC"] * 4
    assert sleeps == [1.0, 2.0, 4.0]


# Exact downstream wording from ContextualWisdomLab/inkspan#160 required
# Strix job 95492526891 (run 32064279893) at 2026-08-17 20:12:47 UTC.
INSTALLATION_RATE_LIMIT_403 = (
    "gh: HTTP 403: API rate limit exceeded for installation ID 141441800 "
    "(https://api.github.com/repos/ContextualWisdomLab/inkspan)"
)
SECONDARY_RATE_LIMIT_403 = (
    "gh: HTTP 403: You have exceeded a secondary rate limit. "
    "Please wait a few minutes before you try again."
)
AUTH_DENIED_403 = "gh: HTTP 403: Resource not accessible by integration"


def test_http_404_and_403_are_not_success_and_are_not_retried() -> None:
    """A missing or unauthorized repository must fail closed immediately."""
    sleeps: list[float] = []
    missing = _ScriptedGh([visibility.VisibilityCommandError("gh: HTTP 404: Not Found")])
    denied = _ScriptedGh([visibility.VisibilityCommandError(AUTH_DENIED_403)])

    with pytest.raises(
        visibility.VisibilityResolutionError,
        match="denied or missing: gh: HTTP 404",
    ):
        visibility.fetch_repository_visibility(
            "ContextualWisdomLab/missing-repo",
            run_gh=missing,
            sleep=sleeps.append,
        )
    with pytest.raises(
        visibility.VisibilityResolutionError,
        match="denied or missing: gh: HTTP 403: Resource not accessible",
    ):
        visibility.fetch_repository_visibility(
            "ContextualWisdomLab/private-denied",
            run_gh=denied,
            sleep=sleeps.append,
        )
    assert missing.calls == ["ContextualWisdomLab/missing-repo"]
    assert denied.calls == ["ContextualWisdomLab/private-denied"]
    assert sleeps == []


def test_installation_rate_limit_403_retries_then_preserves_visibility() -> None:
    """Inkspan installation-budget 403 is transient, not an auth/missing repo."""
    runner = _ScriptedGh(
        [
            visibility.VisibilityCommandError(INSTALLATION_RATE_LIMIT_403),
            "false\n",
        ]
    )
    sleeps: list[float] = []

    assert visibility.classify_gh_failure(INSTALLATION_RATE_LIMIT_403) == "transient"
    assert (
        visibility.fetch_repository_visibility(
            "ContextualWisdomLab/inkspan",
            run_gh=runner,
            sleep=sleeps.append,
        )
        == "false"
    )
    assert runner.calls == ["ContextualWisdomLab/inkspan"] * 2
    assert sleeps == [30.0]


def test_secondary_rate_limit_403_retries_then_preserves_visibility() -> None:
    """Secondary-rate-limit 403 wording is the same transient family."""
    runner = _ScriptedGh(
        [
            visibility.VisibilityCommandError(SECONDARY_RATE_LIMIT_403),
            "true",
        ]
    )
    sleeps: list[float] = []

    assert visibility.classify_gh_failure(SECONDARY_RATE_LIMIT_403) == "transient"
    assert (
        visibility.fetch_repository_visibility(
            "ContextualWisdomLab/inkspan",
            run_gh=runner,
            sleep=sleeps.append,
        )
        == "true"
    )
    assert runner.calls == ["ContextualWisdomLab/inkspan"] * 2
    assert sleeps == [30.0]


def test_exhausted_rate_limit_403_stays_typed_infrastructure_failure() -> None:
    """Quota exhaustion must stay non-passing and must not look like a finding."""
    runner = _ScriptedGh(
        [visibility.VisibilityCommandError(INSTALLATION_RATE_LIMIT_403)] * 3
    )
    sleeps: list[float] = []

    with pytest.raises(
        visibility.VisibilityResolutionError,
        match="GitHub API rate-limit; this is infrastructure, not a source finding",
    ) as excinfo:
        visibility.fetch_repository_visibility(
            "ContextualWisdomLab/inkspan",
            run_gh=runner,
            sleep=sleeps.append,
        )
    assert "installation ID 141441800" in str(excinfo.value)
    assert "denied or missing" not in str(excinfo.value)
    assert runner.calls == ["ContextualWisdomLab/inkspan"] * 3
    assert sleeps == [30.0, 60.0]


def test_rate_limit_403_is_not_confused_with_authorization_403() -> None:
    """Only the authenticated quota family is retryable; other 403s stay closed."""
    assert visibility.classify_gh_failure(INSTALLATION_RATE_LIMIT_403) == "transient"
    assert visibility.classify_gh_failure(SECONDARY_RATE_LIMIT_403) == "transient"
    assert visibility.classify_gh_failure(AUTH_DENIED_403) == "permanent"
    assert (
        visibility.classify_gh_failure("gh: HTTP 403: API rate limit exceeded")
        == "transient"
    )
    assert visibility.classify_gh_failure("gh: HTTP 403: Forbidden") == "permanent"


def test_rate_limit_retry_after_is_honored_and_capped() -> None:
    """Honor Retry-After from gh output, but never sleep an unbounded reset."""
    assert visibility.parse_rate_limit_wait_seconds("Retry-After: 12") == 12.0
    assert (
        visibility.parse_rate_limit_wait_seconds(
            "X-RateLimit-Reset: 1700000010",
            now=1_700_000_000.0,
        )
        == 10.0
    )
    assert (
        visibility.rate_limit_backoff_seconds(
            1,
            "gh: HTTP 403: API rate limit exceeded\nRetry-After: 12",
        )
        == 12.0
    )
    assert (
        visibility.rate_limit_backoff_seconds(
            1,
            "gh: HTTP 403: API rate limit exceeded\nRetry-After: 90",
        )
        == 60.0
    )
    assert (
        visibility.rate_limit_backoff_seconds(
            1,
            "gh: HTTP 403: API rate limit exceeded\nRetry-After: 0",
        )
        == 5.0
    )
    runner = _ScriptedGh(
        [
            visibility.VisibilityCommandError(
                INSTALLATION_RATE_LIMIT_403 + "\nRetry-After: 12"
            ),
            "false",
        ]
    )
    sleeps: list[float] = []
    assert (
        visibility.fetch_repository_visibility(
            "ContextualWisdomLab/inkspan",
            run_gh=runner,
            sleep=sleeps.append,
        )
        == "false"
    )
    assert sleeps == [12.0]


def test_rate_limit_reset_header_and_past_reset_are_bounded() -> None:
    """Honor X-RateLimit-Reset when present; a past reset uses the default wait."""
    assert (
        visibility.parse_rate_limit_wait_seconds(
            "X-RateLimit-Reset: 112", now=100.0
        )
        == 12.0
    )
    assert (
        visibility.parse_rate_limit_wait_seconds(
            "X-RateLimit-Reset: 90", now=100.0
        )
        is None
    )
    assert visibility.parse_rate_limit_wait_seconds("") is None
    assert (
        visibility.rate_limit_backoff_seconds(
            1,
            INSTALLATION_RATE_LIMIT_403 + "\nX-RateLimit-Reset: 1",
            now=8.0,
        )
        == 30.0
    )
    runner = _ScriptedGh(
        [
            visibility.VisibilityCommandError(
                INSTALLATION_RATE_LIMIT_403 + "\nX-RateLimit-Reset: 18"
            ),
            "false",
        ]
    )
    sleeps: list[float] = []
    assert (
        visibility.fetch_repository_visibility(
            "ContextualWisdomLab/inkspan",
            run_gh=runner,
            sleep=sleeps.append,
            now=lambda: 8.0,
        )
        == "false"
    )
    assert sleeps == [10.0]


def test_rate_limit_does_not_shrink_generic_retry_budget() -> None:
    """A later generic transient may still use the full retry budget."""
    runner = _ScriptedGh(
        [
            visibility.VisibilityCommandError(INSTALLATION_RATE_LIMIT_403),
            visibility.VisibilityCommandError("gh: HTTP 502: Bad Gateway"),
            visibility.VisibilityCommandError("gh: HTTP 503: Service Unavailable"),
            "false",
        ]
    )
    sleeps: list[float] = []

    assert (
        visibility.fetch_repository_visibility(
            "ContextualWisdomLab/inkspan",
            run_gh=runner,
            sleep=sleeps.append,
        )
        == "false"
    )
    assert sleeps == [30.0, 2.0, 4.0]


def test_generic_transient_backoff_stays_short() -> None:
    """A 502 flake must keep the original 1/2/4s schedule."""
    assert visibility.backoff_seconds(1) == 1.0
    assert visibility.rate_limit_backoff_seconds(1, INSTALLATION_RATE_LIMIT_403) == 30.0
    assert visibility.RATE_LIMIT_MAX_ATTEMPTS == 3
    assert visibility.DEFAULT_MAX_ATTEMPTS == 4


def test_public_and_private_booleans_are_preserved() -> None:
    """Exact public and private booleans must survive lookup unchanged."""
    public = _ScriptedGh(["false\n"])
    private = _ScriptedGh(["true"])

    assert (
        visibility.fetch_repository_visibility(
            "ContextualWisdomLab/naruon",
            run_gh=public,
            sleep=lambda _delay: None,
        )
        == "false"
    )
    assert (
        visibility.fetch_repository_visibility(
            "ContextualWisdomLab/xtrmLLMBatchPython",
            run_gh=private,
            sleep=lambda _delay: None,
        )
        == "true"
    )


def test_zero_attempts_fail_closed_without_calling_github() -> None:
    """A non-positive retry budget must not invent a visibility boolean."""
    runner = _ScriptedGh(["true"])

    with pytest.raises(
        visibility.VisibilityResolutionError,
        match="at least one attempt",
    ):
        visibility.fetch_repository_visibility(
            "ContextualWisdomLab/aFIPC",
            run_gh=runner,
            sleep=lambda _delay: None,
            max_attempts=0,
        )
    assert runner.calls == []


def test_invalid_repository_fails_closed_without_calling_github() -> None:
    """Targets outside ContextualWisdomLab never become a visibility probe."""
    runner = _ScriptedGh(["true"])

    with pytest.raises(
        visibility.VisibilityResolutionError,
        match="must belong to ContextualWisdomLab",
    ):
        visibility.fetch_repository_visibility(
            "octocat/Hello-World",
            run_gh=runner,
            sleep=lambda _delay: None,
        )
    assert runner.calls == []


def test_unknown_gh_failure_fails_closed_without_retry() -> None:
    """Unclassified API errors are not treated as a successful public repo."""
    runner = _ScriptedGh(
        [visibility.VisibilityCommandError("gh: GraphQL: Field unknown")]
    )
    sleeps: list[float] = []

    with pytest.raises(
        visibility.VisibilityResolutionError,
        match="Field unknown",
    ):
        visibility.fetch_repository_visibility(
            "ContextualWisdomLab/aFIPC",
            run_gh=runner,
            sleep=sleeps.append,
        )
    assert runner.calls == ["ContextualWisdomLab/aFIPC"]
    assert sleeps == []


def test_classify_gh_failure_covers_http_and_marker_families() -> None:
    """HTTP status and timeout/connection markers classify independently."""
    assert visibility.classify_gh_failure("gh: HTTP 401: Bad credentials") == "permanent"
    assert visibility.classify_gh_failure("HTTP/429 Too Many Requests") == "transient"
    assert visibility.classify_gh_failure("gh: HTTP 500: server error") == "transient"
    assert visibility.classify_gh_failure("gh: HTTP 418: teapot") == "unknown"
    assert visibility.classify_gh_failure("connection reset by peer") == "transient"
    assert visibility.classify_gh_failure("unexpected end of JSON input") == "transient"
    assert visibility.classify_gh_failure("") == "unknown"
    assert visibility.parse_private_flag(None) is None
    assert visibility.backoff_seconds(4) == 4.0
    with pytest.raises(
        visibility.VisibilityResolutionError,
        match="must belong to ContextualWisdomLab",
    ):
        visibility.validate_target_repository("   ")


def test_run_gh_visibility_success_timeout_oserror_and_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real ``gh api`` wrapper maps process outcomes to typed failures."""

    def succeed(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert argv == ["gh", "api", "repos/ContextualWisdomLab/aFIPC", "--jq", ".private"]
        assert kwargs["shell"] is False
        return subprocess.CompletedProcess(argv, 0, stdout="false\n", stderr="")

    monkeypatch.setattr(visibility.subprocess, "run", succeed)
    assert visibility.run_gh_visibility("ContextualWisdomLab/aFIPC") == "false\n"

    def timeout(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(visibility.subprocess, "run", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        visibility.run_gh_visibility("ContextualWisdomLab/aFIPC")

    def missing_binary(
        argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("gh")

    monkeypatch.setattr(visibility.subprocess, "run", missing_binary)
    with pytest.raises(visibility.VisibilityCommandError, match="could not start"):
        visibility.run_gh_visibility("ContextualWisdomLab/aFIPC")

    def fail_empty(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 2, stdout="", stderr="")

    monkeypatch.setattr(visibility.subprocess, "run", fail_empty)
    with pytest.raises(visibility.VisibilityCommandError, match="exited 2"):
        visibility.run_gh_visibility("ContextualWisdomLab/aFIPC")

    def fail_token(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            argv,
            1,
            stdout="",
            stderr="Authorization: ghs_secretvalue123",
        )

    monkeypatch.setattr(visibility.subprocess, "run", fail_token)
    with pytest.raises(visibility.VisibilityCommandError, match="<redacted>"):
        visibility.run_gh_visibility("ContextualWisdomLab/aFIPC")


def test_cli_writes_visibility_and_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The workflow entrypoint writes ``is_private`` or exits 1 fail-closed."""
    output = tmp_path / "github-output"
    output.write_text("existing=1\n", encoding="utf-8")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("TARGET_REPOSITORY", raising=False)
    monkeypatch.setattr(
        visibility,
        "fetch_repository_visibility",
        lambda repository: "false" if repository.endswith("naruon") else "true",
    )

    assert (
        visibility.main(
            [
                "--repository",
                "ContextualWisdomLab/naruon",
                "--github-output",
                str(output),
            ]
        )
        == 0
    )
    assert output.read_text(encoding="utf-8") == "existing=1\nis_private=false\n"

    assert visibility.main(["--repository", "ContextualWisdomLab/naruon"]) == 1

    def deny(_repository: str) -> str:
        raise visibility.VisibilityResolutionError("denied")

    monkeypatch.setattr(visibility, "fetch_repository_visibility", deny)
    assert (
        visibility.main(
            [
                "--repository",
                "ContextualWisdomLab/naruon",
                "--github-output",
                str(output),
            ]
        )
        == 1
    )


def test_cli_main_module_uses_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``python3 strix_resolve_target_visibility.py`` reads workflow env vars."""
    output = tmp_path / "github-output"
    monkeypatch.setenv("TARGET_REPOSITORY", "ContextualWisdomLab/aFIPC")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(sys, "argv", ["strix_resolve_target_visibility.py"])

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert argv[-1] == ".private"
        return subprocess.CompletedProcess(argv, 0, stdout="true\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_path(
            str(REPO_ROOT / "scripts" / "ci" / "strix_resolve_target_visibility.py"),
            run_name="__main__",
        )

    assert excinfo.value.code == 0
    assert output.read_text(encoding="utf-8") == "is_private=true\n"


def test_workflow_step_parser_names_a_missing_step() -> None:
    """A missing step name must fail with the requested name, not IndexError."""
    with pytest.raises(AssertionError, match="workflow step not found: Missing Step"):
        _workflow_step("jobs:\n  strix:\n    steps: []\n", "Missing Step")


def test_strix_workflow_uses_helper_and_keeps_token_order() -> None:
    """The required Strix job must call the helper with the existing token chain."""
    workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
    export_step = _workflow_step(workflow, "Export trusted Strix source paths")
    visibility_step = _workflow_step(workflow, "Resolve target repository visibility")

    assert (
        'test -f "$trusted_strix_source/scripts/ci/strix_resolve_target_visibility.py"'
        in export_step
    )
    assert (
        'python3 "$TRUSTED_STRIX_SOURCE/scripts/ci/strix_resolve_target_visibility.py"'
        in visibility_step
    )
    assert (
        "GH_TOKEN: ${{ steps.target_app_token.outputs.token || "
        "secrets.OPENCODE_APPROVE_TOKEN || github.token }}"
    ) in visibility_step
    assert "COPILOT_GITHUB_TOKEN" not in visibility_step
    assert "COPILOT_GITHUB_TOKEN" not in workflow
    assert 'is_private="$(gh api "repos/${TARGET_REPOSITORY}" --jq \'.private\')"' not in (
        workflow
    )
    assert "STRIX_SCAN_MODE" not in visibility_step


def test_noema_and_opencode_visibility_paths_stay_untouched() -> None:
    """This slice must not change Noema or OpenCode review workflows."""
    noema = NOEMA_WORKFLOW.read_text(encoding="utf-8")
    opencode = (
        REPO_ROOT / ".github" / "workflows" / "opencode-review.yml"
    ).read_text(encoding="utf-8")

    assert 'is_private="$(gh api "repos/${TARGET_REPOSITORY}" --jq \'.private\')"' in (
        noema
    )
    assert "strix_resolve_target_visibility.py" not in noema
    assert "strix_resolve_target_visibility.py" not in opencode
