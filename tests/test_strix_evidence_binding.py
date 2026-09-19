"""Contract tests for Strix evidence binding (#2159, #2168)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.ci import strix_evidence_binding as binding


BASE = "a" * 40
HEAD = "b" * 40
OTHER = "c" * 40


def _pr_binding(**overrides: Any) -> binding.PullRequestBinding:
    """Build a live-open PR binding with optional field overrides."""

    payload = {
        "repository": "ContextualWisdomLab/example",
        "pull_request": 2106,
        "state": "open",
        "base_ref": "main",
        "base_sha": BASE,
        "head_sha": HEAD,
    }
    payload.update(overrides)
    return binding.PullRequestBinding(**payload)


def test_binding_requires_live_open_full_shas() -> None:
    """Incomplete or closed PR tuples fail closed before attribution."""

    with pytest.raises(binding.EvidenceBindingError, match="live and open"):
        _pr_binding(state="closed").require_live_open()
    with pytest.raises(binding.EvidenceBindingError, match="40-character"):
        _pr_binding(base_sha="abc").require_live_open()
    with pytest.raises(binding.EvidenceBindingError, match="must differ"):
        _pr_binding(head_sha=BASE).require_live_open()


def test_changed_source_finding_is_pr_delta() -> None:
    """A finding on an authenticated changed hunk is PR-delta evidence."""

    changed = (
        binding.ChangedPath(
            path="docs/codeql.md",
            status="modified",
            changed_lines=frozenset({12, 13}),
        ),
    )
    verdict = binding.classify_finding_scope(
        _pr_binding(),
        changed,
        binding.FindingLocation("docs/codeql.md", 12, 12),
    )
    assert verdict.scope is binding.EvidenceScope.PR_DELTA
    assert binding.pr_delta_findings_block_merge([verdict])


def test_completely_base_identical_source_finding_is_repository_baseline() -> None:
    """#2106-style findings against unchanged protected-base source stay baseline."""

    changed = (
        binding.ChangedPath(
            path="docs/codeql.md",
            status="modified",
            changed_lines=frozenset({1}),
        ),
    )
    verdict = binding.classify_finding_scope(
        _pr_binding(),
        changed,
        binding.FindingLocation("scripts/ci/pingora_edge_policy.py", 40, 45),
    )
    assert verdict.scope is binding.EvidenceScope.REPOSITORY_BASELINE
    assert "base-identical" in verdict.reason
    assert binding.baseline_only_findings([verdict])
    assert not binding.pr_delta_findings_block_merge([verdict])


def test_unchanged_dependency_context_is_context_dependency() -> None:
    """Context closure findings are labeled separately from the PR delta."""

    changed = (
        binding.ChangedPath(
            path="backend/app/routes.py",
            status="modified",
            changed_lines=frozenset({8}),
        ),
    )
    verdict = binding.classify_finding_scope(
        _pr_binding(),
        changed,
        binding.FindingLocation("backend/app/models.py", 3, 3),
        context_dependency_paths=frozenset({"backend/app/models.py"}),
    )
    assert verdict.scope is binding.EvidenceScope.CONTEXT_DEPENDENCY
    assert binding.baseline_only_findings([verdict])


def test_changed_path_nonintersecting_line_is_baseline_not_pr_delta() -> None:
    """Same changed path but outside every hunk is not a PR-delta finding."""

    changed = (
        binding.ChangedPath(
            path="frontend/src/App.tsx",
            status="modified",
            changed_lines=frozenset({40, 41}),
        ),
    )
    verdict = binding.classify_finding_scope(
        _pr_binding(),
        changed,
        binding.FindingLocation("frontend/src/App.tsx", 1, 1),
    )
    assert verdict.scope is binding.EvidenceScope.REPOSITORY_BASELINE


def test_rename_maps_previous_and_current_paths_to_pr_delta() -> None:
    """Renamed files attribute findings via previous_filename or filename."""

    changed = (
        binding.ChangedPath(
            path="src/new_name.py",
            status="renamed",
            previous_path="src/old_name.py",
            changed_lines=frozenset({5}),
        ),
    )
    for path in ("src/new_name.py", "src/old_name.py"):
        verdict = binding.classify_finding_scope(
            _pr_binding(),
            changed,
            binding.FindingLocation(path, 5, 5),
        )
        assert verdict.scope is binding.EvidenceScope.PR_DELTA
        assert verdict.path == "src/new_name.py"


def test_stale_head_and_stacked_base_reports_fail_closed() -> None:
    """Reports bound to the wrong base or head cannot authorize attribution."""

    changed = (
        binding.ChangedPath(path="a.py", status="modified", changed_lines=frozenset({1})),
    )
    with pytest.raises(binding.EvidenceBindingError, match="stale-head"):
        binding.classify_finding_scope(
            _pr_binding(),
            changed,
            binding.FindingLocation("a.py", 1, 1),
            report_head_sha=OTHER,
        )
    with pytest.raises(binding.EvidenceBindingError, match="stacked-base"):
        binding.classify_finding_scope(
            _pr_binding(),
            changed,
            binding.FindingLocation("a.py", 1, 1),
            report_base_sha=OTHER,
        )


def test_empty_changed_inventory_fails_closed() -> None:
    """Attribution cannot proceed without an authenticated changed-file set."""

    with pytest.raises(binding.EvidenceBindingError, match="changed-file inventory"):
        binding.classify_finding_scope(
            _pr_binding(),
            (),
            binding.FindingLocation("a.py", 1, 1),
        )


def test_unsafe_finding_path_is_unmapped() -> None:
    """Traversal and absolute finding paths cannot become PR-delta evidence."""

    changed = (
        binding.ChangedPath(path="safe.py", status="added", changed_lines=frozenset({1})),
    )
    verdict = binding.classify_finding_scope(
        _pr_binding(),
        changed,
        binding.FindingLocation("../secret.py", 1, 1),
    )
    assert verdict.scope is binding.EvidenceScope.UNMAPPED


def test_parse_changed_lines_from_patch() -> None:
    """Unified-diff hunks yield only added/context head-side line numbers."""

    patch = (
        "@@ -10,3 +10,4 @@\n"
        " keep\n"
        "-old\n"
        "+new\n"
        "+extra\n"
        " tail\n"
    )
    assert binding.parse_changed_lines_from_patch(patch) == frozenset({11, 12})


def test_load_changed_paths_from_github_paginates_and_keeps_renames() -> None:
    """GitHub inventory loader pages to completion and preserves rename metadata."""

    pages = [
        [
            {
                "filename": f"f{index}.py",
                "status": "modified",
                "patch": "@@ -1 +1 @@\n-old\n+new\n",
            }
            for index in range(100)
        ],
        [
            {
                "filename": "renamed.py",
                "previous_filename": "legacy.py",
                "status": "renamed",
                "patch": "@@ -2 +2 @@\n-a\n+b\n",
            }
        ],
    ]
    calls: list[str] = []

    def opener(url: str, token: str) -> list[dict[str, Any]]:
        assert token == "token"
        calls.append(url)
        return pages[len(calls) - 1]

    rows = binding.load_changed_paths_from_github(
        "https://api.github.com",
        "ContextualWisdomLab/example",
        2106,
        "token",
        opener=opener,
    )
    assert len(calls) == 2
    assert len(rows) == 101
    assert rows[-1].previous_path == "legacy.py"
    assert 2 in rows[-1].changed_lines


def test_apply_patch_miss_rejects_already_applied_claim(tmp_path: Path) -> None:
    """#2168: failed apply_patch cannot be summarized as already applied."""

    log_text = (
        "WorkspaceReadNotFoundError: file not found: /workspace/backend/app/main.py\n"
        "agents.sandbox.errors.ApplyPatchFileNotFoundError: "
        "apply_patch missing file: backend/app/main.py\n"
    )
    report_text = (
        "Medium CWE-862 finding. The immediate fix was already applied in "
        "backend/app/main.py and syntax-verified.\n"
    )
    events = binding.detect_apply_patch_failures(log_text)
    assert events and events[0].success is False

    verdict = binding.classify_remediation(
        finding_confirmed=True,
        fix_proposed=True,
        tool_events=events,
        workspace_root=tmp_path,
        relative_path="backend/app/main.py",
        expected_snippet="def secure():",
        source_commit_sha=None,
        report_claims_already_applied=True,
    )
    assert verdict.state is binding.RemediationState.REMEDIATION_FAILED
    assert verdict.allows_already_applied_claim is False

    cleaned = binding.sanitize_remediation_report_text(report_text, log_text)
    assert "already applied" not in cleaned.casefold()
    assert "remediation NOT applied" in cleaned
    assert binding.RemediationState.REMEDIATION_FAILED.value in cleaned


def test_workspace_byte_proof_allows_scan_workspace_applied(tmp_path: Path) -> None:
    """A fix is applied-in-scan only after exact workspace bytes contain the diff."""

    target = tmp_path / "backend" / "app" / "main.py"
    target.parent.mkdir(parents=True)
    target.write_text("def secure():\n    return True\n", encoding="utf-8")

    verdict = binding.classify_remediation(
        finding_confirmed=True,
        fix_proposed=True,
        tool_events=(),
        workspace_root=tmp_path,
        relative_path="backend/app/main.py",
        expected_snippet="def secure():",
        source_commit_sha=None,
        report_claims_already_applied=True,
    )
    assert verdict.state is binding.RemediationState.FIX_APPLIED_IN_SCAN_WORKSPACE
    assert verdict.allows_already_applied_claim is True


def test_source_commit_receipt_is_required_for_committed_state() -> None:
    """Isolated sandbox mutation is never described as source-repository mutation."""

    verdict = binding.classify_remediation(
        finding_confirmed=True,
        fix_proposed=True,
        tool_events=(),
        workspace_root=None,
        relative_path=None,
        expected_snippet=None,
        source_commit_sha=HEAD,
        report_claims_already_applied=True,
    )
    assert verdict.state is binding.RemediationState.FIX_COMMITTED_TO_SOURCE

    with pytest.raises(binding.EvidenceBindingError, match="full SHA"):
        binding.classify_remediation(
            finding_confirmed=True,
            fix_proposed=False,
            tool_events=(),
            workspace_root=None,
            relative_path=None,
            expected_snippet=None,
            source_commit_sha="short",
            report_claims_already_applied=False,
        )


def test_cli_classify_finding_and_sanitize(tmp_path: Path) -> None:
    """CLI surfaces JSON verdicts and sanitizes false remediation prose."""

    binding_path = tmp_path / "binding.json"
    changed_path = tmp_path / "changed.json"
    binding_path.write_text(
        json.dumps(
            {
                "repository": "ContextualWisdomLab/example",
                "pull_request": 2106,
                "state": "open",
                "base_ref": "main",
                "base_sha": BASE,
                "head_sha": HEAD,
            }
        ),
        encoding="utf-8",
    )
    changed_path.write_text(
        json.dumps(
            [
                {
                    "path": "docs/a.md",
                    "status": "modified",
                    "changed_lines": [3],
                    "patch_available": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    assert (
        binding.main(
            [
                "classify-finding",
                "--binding-json",
                str(binding_path),
                "--changed-paths-json",
                str(changed_path),
                "--path",
                "scripts/ci/pingora_edge_policy.py",
                "--start-line",
                "10",
            ]
        )
        == 0
    )

    report = tmp_path / "report.md"
    log = tmp_path / "strix.log"
    out = tmp_path / "clean.md"
    report.write_text("fix already applied in backend/app/main.py", encoding="utf-8")
    log.write_text(
        "ApplyPatchFileNotFoundError: apply_patch missing file: backend/app/main.py",
        encoding="utf-8",
    )
    assert (
        binding.main(
            [
                "sanitize-report",
                "--report-file",
                str(report),
                "--log-file",
                str(log),
                "--output-file",
                str(out),
            ]
        )
        == 0
    )
    assert "NOT applied" in out.read_text(encoding="utf-8")


def test_cli_classify_remediation_fails_closed_on_patch_miss(tmp_path: Path) -> None:
    """classify-remediation exits non-zero when already-applied claims are false."""

    report = tmp_path / "report.md"
    log = tmp_path / "strix.log"
    report.write_text("already applied", encoding="utf-8")
    log.write_text(
        "WorkspaceReadNotFoundError: file not found: /workspace/backend/app/main.py",
        encoding="utf-8",
    )
    assert (
        binding.main(
            [
                "classify-remediation",
                "--report-file",
                str(report),
                "--log-file",
                str(log),
                "--finding-confirmed",
                "--fix-proposed",
            ]
        )
        == 2
    )


def test_load_changed_paths_rejects_malformed_payload() -> None:
    """Malformed GitHub pages fail closed instead of truncating evidence."""

    def opener(_url: str, _token: str) -> dict[str, str]:
        return {"not": "a-list"}

    with pytest.raises(binding.EvidenceBindingError, match="JSON array"):
        binding.load_changed_paths_from_github(
            "https://api.github.com",
            "ContextualWisdomLab/example",
            1,
            "token",
            opener=opener,
        )


def test_path_level_pr_delta_when_patch_truncated() -> None:
    """Missing inline patches still prove the path changed at path scope."""

    changed = (
        binding.ChangedPath(
            path="large.bin",
            status="modified",
            changed_lines=frozenset(),
            patch_available=False,
        ),
    )
    verdict = binding.classify_finding_scope(
        _pr_binding(),
        changed,
        binding.FindingLocation("large.bin", 9, 9),
    )
    assert verdict.scope is binding.EvidenceScope.PR_DELTA


def test_binding_rejects_malformed_identity_fields() -> None:
    """Repository, PR number, base ref, and head SHA shape fail closed."""

    with pytest.raises(binding.EvidenceBindingError, match="owner/name"):
        _pr_binding(repository="noneslash").require_live_open()
    with pytest.raises(binding.EvidenceBindingError, match="positive integer"):
        _pr_binding(pull_request=0).require_live_open()
    with pytest.raises(binding.EvidenceBindingError, match="base_ref"):
        _pr_binding(base_ref="  ").require_live_open()
    with pytest.raises(binding.EvidenceBindingError, match="head_sha"):
        _pr_binding(head_sha="zzz").require_live_open()


def test_parse_patch_handles_deletions_escapes_and_zero_count_hunks() -> None:
    """Deletion-only and escaped hunk lines do not invent head-side numbers."""

    patch = "\n".join(
        [
            " preamble before any hunk is ignored",
            "@@ -5,0 +5,0 @@",
            " dangling line while current hunk is inactive",
            "@@ -10,2 +10,1 @@",
            " keep",
            "-gone",
            "\\ No newline at end of file",
            "+++ ignored",
            "--- ignored",
        ]
    )
    assert binding.parse_changed_lines_from_patch(patch) == frozenset()


def test_path_only_changed_finding_is_pr_delta() -> None:
    """A changed path without a claimed line is still PR-delta evidence."""

    changed = (
        binding.ChangedPath(
            path="docs/a.md",
            status="modified",
            changed_lines=frozenset({3}),
        ),
    )
    verdict = binding.classify_finding_scope(
        _pr_binding(),
        changed,
        binding.FindingLocation("docs/a.md"),
    )
    assert verdict.scope is binding.EvidenceScope.PR_DELTA


def test_nonpositive_and_inverted_line_ranges_are_unmapped() -> None:
    """Line-level claims must use a positive, non-inverted range."""

    changed = (
        binding.ChangedPath(
            path="docs/a.md",
            status="modified",
            changed_lines=frozenset({3}),
        ),
    )
    assert (
        binding.classify_finding_scope(
            _pr_binding(),
            changed,
            binding.FindingLocation("docs/a.md", 0, 0),
        ).scope
        is binding.EvidenceScope.UNMAPPED
    )
    assert (
        binding.classify_finding_scope(
            _pr_binding(),
            changed,
            binding.FindingLocation("docs/a.md", 5, 2),
        ).scope
        is binding.EvidenceScope.UNMAPPED
    )


def test_matching_report_head_and_base_accept_exact_tuple() -> None:
    """Exact matching report SHAs authorize attribution."""

    changed = (
        binding.ChangedPath(path="a.py", status="added", changed_lines=frozenset({1})),
    )
    verdict = binding.classify_finding_scope(
        _pr_binding(),
        changed,
        binding.FindingLocation("a.py", 1, 1),
        report_head_sha=HEAD,
        report_base_sha=BASE,
    )
    assert verdict.scope is binding.EvidenceScope.PR_DELTA


def test_malformed_report_shas_fail_closed() -> None:
    """Missing or short report SHAs cannot authorize attribution."""

    changed = (
        binding.ChangedPath(path="a.py", status="added", changed_lines=frozenset({1})),
    )
    with pytest.raises(binding.EvidenceBindingError, match="report head SHA"):
        binding.require_matching_report_head(_pr_binding(), None)
    with pytest.raises(binding.EvidenceBindingError, match="report head SHA"):
        binding.require_matching_report_head(_pr_binding(), "abcd")
    with pytest.raises(binding.EvidenceBindingError, match="report base SHA"):
        binding.require_matching_report_base(_pr_binding(), None)
    with pytest.raises(binding.EvidenceBindingError, match="report base SHA"):
        binding.require_matching_report_base(_pr_binding(), "abcd")


def test_load_changed_paths_rejects_invalid_entries_and_cap() -> None:
    """Malformed rows and oversized inventories fail closed."""

    def bad_entry(_url: str, _token: str) -> list[object]:
        return ["not-an-object"]

    with pytest.raises(binding.EvidenceBindingError, match="not an object"):
        binding.load_changed_paths_from_github(
            "https://api.github.com", "ContextualWisdomLab/example", 1, "t", opener=bad_entry
        )

    def bad_fields(_url: str, _token: str) -> list[dict[str, object]]:
        return [{"filename": "", "status": "modified", "patch": None}]

    with pytest.raises(binding.EvidenceBindingError, match="invalid fields"):
        binding.load_changed_paths_from_github(
            "https://api.github.com", "ContextualWisdomLab/example", 1, "t", opener=bad_fields
        )

    def bad_previous(_url: str, _token: str) -> list[dict[str, object]]:
        return [
            {
                "filename": "a.py",
                "status": "renamed",
                "previous_filename": 1,
                "patch": None,
            }
        ]

    with pytest.raises(binding.EvidenceBindingError, match="previous_filename"):
        binding.load_changed_paths_from_github(
            "https://api.github.com", "ContextualWisdomLab/example", 1, "t", opener=bad_previous
        )

    def bad_patch(_url: str, _token: str) -> list[dict[str, object]]:
        return [{"filename": "a.py", "status": "modified", "patch": 12}]

    with pytest.raises(binding.EvidenceBindingError, match="patch must be a string"):
        binding.load_changed_paths_from_github(
            "https://api.github.com", "ContextualWisdomLab/example", 1, "t", opener=bad_patch
        )

    calls = {"n": 0}

    def oversized(_url: str, _token: str) -> list[dict[str, object]]:
        calls["n"] += 1
        return [
            {
                "filename": f"f{calls['n']}-{index}.py",
                "status": "modified",
                "patch": None,
            }
            for index in range(100)
        ]

    # Force the in-loop cap by temporarily lowering MAX_CHANGED_FILES.
    original = binding.MAX_CHANGED_FILES
    try:
        binding.MAX_CHANGED_FILES = 50  # type: ignore[misc]
        with pytest.raises(binding.EvidenceBindingError, match="exceeded"):
            binding.load_changed_paths_from_github(
                "https://api.github.com",
                "ContextualWisdomLab/example",
                1,
                "t",
                opener=oversized,
            )
    finally:
        binding.MAX_CHANGED_FILES = original  # type: ignore[misc]


def test_default_github_opener_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """Token, HTTP, network, and JSON failures fail closed."""

    from io import BytesIO

    with pytest.raises(binding.EvidenceBindingError, match="token is required"):
        binding.default_github_opener("https://api.github.com/x", "")

    def raise_http(*_args: object, **_kwargs: object) -> object:
        raise binding.HTTPError(
            "https://api.github.com/x",
            403,
            "Forbidden",
            hdrs=None,
            fp=BytesIO(),
        )

    monkeypatch.setattr(binding._GITHUB_API_OPENER, "open", raise_http)
    with pytest.raises(binding.EvidenceBindingError, match="HTTP 403"):
        binding.default_github_opener("https://api.github.com/x", "token")

    def raise_url(*_args: object, **_kwargs: object) -> object:
        raise binding.URLError("down")

    monkeypatch.setattr(binding._GITHUB_API_OPENER, "open", raise_url)
    with pytest.raises(binding.EvidenceBindingError, match="URLError"):
        binding.default_github_opener("https://api.github.com/x", "token")

    class Response:
        """Fake successful HTTP response with invalid JSON bytes."""

        def read(self) -> bytes:
            """Return non-JSON payload bytes."""

            return b"not-json"

        def __enter__(self) -> "Response":
            """Enter the context manager."""

            return self

        def __exit__(self, *_args: object) -> None:
            """Exit the context manager."""

            return None

    monkeypatch.setattr(binding._GITHUB_API_OPENER, "open", lambda *_a, **_k: Response())
    with pytest.raises(binding.EvidenceBindingError, match="not JSON"):
        binding.default_github_opener("https://api.github.com/x", "token")


def test_default_github_opener_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """A well-formed GitHub JSON body is returned decoded."""

    class Response:
        """Fake successful HTTP response."""

        def read(self) -> bytes:
            """Return a JSON array payload."""

            return b'[{"filename":"a.py","status":"added","patch":null}]'

        def __enter__(self) -> "Response":
            """Enter the context manager."""

            return self

        def __exit__(self, *_args: object) -> None:
            """Exit the context manager."""

            return None

    monkeypatch.setattr(binding._GITHUB_API_OPENER, "open", lambda *_a, **_k: Response())
    rows = binding.load_changed_paths_from_github(
        "https://api.github.com",
        "ContextualWisdomLab/example",
        1,
        "token",
    )
    assert rows[0].path == "a.py"
    assert rows[0].patch_available is False


def test_apply_patch_failure_without_path_and_without_already_applied_claim() -> None:
    """Tool failures without a path still fail closed; claims are optional."""

    events = binding.detect_apply_patch_failures(
        "ApplyPatchFileNotFoundError: something went wrong without a path marker\n"
    )
    assert events[0].target_path == "unknown"
    verdict = binding.classify_remediation(
        finding_confirmed=True,
        fix_proposed=False,
        tool_events=events,
        workspace_root=None,
        relative_path=None,
        expected_snippet=None,
        source_commit_sha=None,
        report_claims_already_applied=False,
    )
    assert verdict.state is binding.RemediationState.REMEDIATION_FAILED


def test_workspace_diff_helpers_reject_unsafe_and_missing(tmp_path: Path) -> None:
    """Workspace proof rejects empty snippets, unsafe paths, and missing files."""

    assert binding.workspace_contains_expected_diff(tmp_path, "a.py", "") is False
    assert binding.workspace_contains_expected_diff(tmp_path, "../x", "x") is False
    assert binding.workspace_contains_expected_diff(tmp_path, "missing.py", "x") is False
    link = tmp_path / "link.py"
    target = tmp_path / "real.py"
    target.write_text("body", encoding="utf-8")
    link.symlink_to(target)
    assert binding.workspace_contains_expected_diff(tmp_path, "link.py", "body") is False


def test_classify_remediation_proposed_confirmed_and_false_claim(tmp_path: Path) -> None:
    """Proposed and confirmed states are distinct from false already-applied claims."""

    assert (
        binding.classify_remediation(
            finding_confirmed=True,
            fix_proposed=True,
            tool_events=(),
            workspace_root=tmp_path,
            relative_path="a.py",
            expected_snippet="missing",
            source_commit_sha=None,
            report_claims_already_applied=False,
        ).state
        is binding.RemediationState.FIX_PROPOSED
    )
    assert (
        binding.classify_remediation(
            finding_confirmed=True,
            fix_proposed=False,
            tool_events=(),
            workspace_root=None,
            relative_path=None,
            expected_snippet=None,
            source_commit_sha=None,
            report_claims_already_applied=False,
        ).state
        is binding.RemediationState.FINDING_CONFIRMED
    )
    assert (
        binding.classify_remediation(
            finding_confirmed=True,
            fix_proposed=False,
            tool_events=(),
            workspace_root=None,
            relative_path=None,
            expected_snippet=None,
            source_commit_sha=None,
            report_claims_already_applied=True,
        ).state
        is binding.RemediationState.REMEDIATION_FAILED
    )
    with pytest.raises(binding.EvidenceBindingError, match="incomplete"):
        binding.classify_remediation(
            finding_confirmed=False,
            fix_proposed=False,
            tool_events=(),
            workspace_root=None,
            relative_path=None,
            expected_snippet=None,
            source_commit_sha=None,
            report_claims_already_applied=False,
        )


def test_sanitize_noop_and_baseline_helpers() -> None:
    """Sanitize is a no-op without failures; helpers cover empty mapped sets."""

    assert binding.sanitize_remediation_report_text("already applied", "clean log") == (
        "already applied"
    )
    assert binding.baseline_only_findings([]) is False
    unmapped = binding.FindingScopeVerdict(
        scope=binding.EvidenceScope.UNMAPPED,
        path="x",
        reason="r",
    )
    assert binding.baseline_only_findings([unmapped]) is False


def test_cli_stdout_sanitize_and_error_paths(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI writes sanitized text to stdout and maps parse errors to exit 2."""

    report = tmp_path / "report.md"
    log = tmp_path / "strix.log"
    report.write_text("no remediation claim", encoding="utf-8")
    log.write_text("clean", encoding="utf-8")
    assert (
        binding.main(
            [
                "sanitize-report",
                "--report-file",
                str(report),
                "--log-file",
                str(log),
            ]
        )
        == 0
    )
    assert "no remediation claim" in capsys.readouterr().out

    bad_binding = tmp_path / "bad.json"
    bad_binding.write_text("{", encoding="utf-8")
    assert (
        binding.main(
            [
                "classify-finding",
                "--binding-json",
                str(bad_binding),
                "--changed-paths-json",
                str(bad_binding),
                "--path",
                "a.py",
            ]
        )
        == 2
    )

    # Force the terminal fallback return by calling main with no matched command
    # after argparse would normally prevent it — cover via classify with bad shape.
    changed = tmp_path / "changed.json"
    changed.write_text(
        json.dumps([{"path": "a.py", "status": "modified", "changed_lines": ["x"]}]),
        encoding="utf-8",
    )
    good_binding = tmp_path / "good.json"
    good_binding.write_text(
        json.dumps(
            {
                "repository": "ContextualWisdomLab/example",
                "pull_request": 1,
                "state": "open",
                "base_ref": "main",
                "base_sha": BASE,
                "head_sha": HEAD,
            }
        ),
        encoding="utf-8",
    )
    assert (
        binding.main(
            [
                "classify-finding",
                "--binding-json",
                str(good_binding),
                "--changed-paths-json",
                str(changed),
                "--path",
                "a.py",
            ]
        )
        == 2
    )


def test_cli_unmapped_finding_exits_two(tmp_path: Path) -> None:
    """classify-finding exits 2 when the finding path is unmapped."""

    binding_path = tmp_path / "binding.json"
    changed_path = tmp_path / "changed.json"
    binding_path.write_text(
        json.dumps(
            {
                "repository": "ContextualWisdomLab/example",
                "pull_request": 2106,
                "state": "open",
                "base_ref": "main",
                "base_sha": BASE,
                "head_sha": HEAD,
            }
        ),
        encoding="utf-8",
    )
    changed_path.write_text(
        json.dumps(
            [
                {
                    "path": "docs/a.md",
                    "status": "modified",
                    "changed_lines": [3],
                    "patch_available": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    assert (
        binding.main(
            [
                "classify-finding",
                "--binding-json",
                str(binding_path),
                "--changed-paths-json",
                str(changed_path),
                "--path",
                "../secret.py",
                "--start-line",
                "1",
            ]
        )
        == 2
    )


def test_workspace_read_oserror_returns_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unreadable workspace file cannot prove a remediation diff."""

    target = tmp_path / "a.py"
    target.write_text("body", encoding="utf-8")

    def boom(self: Path, *_args: object, **_kwargs: object) -> str:
        raise OSError("denied")

    monkeypatch.setattr(Path, "read_text", boom)
    assert binding.workspace_contains_expected_diff(tmp_path, "a.py", "body") is False


def test_workspace_missing_root_returns_false(tmp_path: Path) -> None:
    """A missing workspace root cannot authorize remediation byte proof."""

    missing = tmp_path / "missing-root"
    assert binding.workspace_contains_expected_diff(missing, "a.py", "body") is False


def test_default_github_opener_refuses_a_non_github_origin() -> None:
    """The opener takes a string, so it must pin the origin itself.

    Without this, an unexpected caller could make it fetch any scheme or host,
    including file:// or an internal address. Semgrep's dynamic-urllib audit
    rule is what surfaced the gap.
    """
    import importlib.util
    import sys
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "strix_evidence_binding", Path("scripts/ci/strix_evidence_binding.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["strix_evidence_binding"] = module
    spec.loader.exec_module(module)

    assert (
        module._require_github_api_url("https://api.github.com/repos/o/r")
        == "https://api.github.com/repos/o/r"
    )
    for rejected in (
        "http://api.github.com/repos/o/r",
        "https://api.github.com.evil.example/repos/o/r",
        "file:///etc/passwd",
    ):
        try:
            module._require_github_api_url(rejected)
        exce