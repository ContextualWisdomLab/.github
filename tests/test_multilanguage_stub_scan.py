from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci import organization_production_stub_scan as scan


def write_source(tmp_path: Path, relative_path: str, content: str) -> Path:
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_javascript_typescript_and_go_runtime_placeholders_fail(tmp_path: Path) -> None:
    write_source(
        tmp_path,
        "server/app.mjs",
        """export function checkout() {\n  throw new Error('Not implemented');\n}\n""",
    )
    write_source(
        tmp_path,
        "src/adapter.ts",
        """export const load = () => Promise.reject(new Error(\"TODO: provider adapter\"));\n""",
    )
    write_source(
        tmp_path,
        "cmd/service.go",
        """package main\nfunc writeback() { panic(\"not implemented\") }\n""",
    )

    findings, errors = scan.scan_changed_paths(
        tmp_path,
        [Path("server/app.mjs"), Path("src/adapter.ts"), Path("cmd/service.go")],
    )

    assert errors == []
    assert [(item.path, item.line, item.reason) for item in findings] == [
        ("cmd/service.go", 2, "panics with an explicit not-implemented marker"),
        ("server/app.mjs", 2, "throws an explicit not-implemented error"),
        ("src/adapter.ts", 1, "rejects with an explicit TODO implementation error"),
    ]


@pytest.mark.parametrize("suffix", ["java", "kt", "kts", "cs"])
def test_jvm_and_dotnet_not_implemented_exceptions_fail(
    tmp_path: Path, suffix: str
) -> None:
    """Recognize explicit implementation exceptions in every supported dialect."""
    relative_path = Path(f"src/Service.{suffix}")
    write_source(
        tmp_path,
        relative_path.as_posix(),
        'throw new UnsupportedOperationException("TODO: implement provider");\n',
    )

    findings, errors = scan.scan_changed_paths(tmp_path, [relative_path])

    assert errors == []
    assert [(item.path, item.line, item.reason) for item in findings] == [
        (
            relative_path.as_posix(),
            1,
            "throws an explicit not-implemented exception",
        )
    ]


def test_runtime_stub_markers_and_demo_success_paths_are_inventory_findings(
    tmp_path: Path,
) -> None:
    write_source(
        tmp_path,
        "server/billing.mjs",
        """// Stripe webhook (stub).\nexport const result = { url: '/?billing=mock', mock: true };\n""",
    )
    write_source(
        tmp_path,
        "backend/webdav_service.py",
        """def sync():\n    # Mock implementation\n    return True\n\nDEMO_USER = 'demo_user'\n""",
    )

    findings, errors = scan.scan_changed_paths(
        tmp_path,
        [Path("server/billing.mjs"), Path("backend/webdav_service.py")],
    )

    assert errors == []
    reasons = {(item.path, item.reason) for item in findings}
    assert ("server/billing.mjs", "explicit runtime stub marker") in reasons
    assert ("server/billing.mjs", "demo-only mock success path in runtime code") in reasons
    assert ("backend/webdav_service.py", "explicit runtime mock marker") in reasons
    assert ("backend/webdav_service.py", "hard-coded demo principal in runtime code") in reasons


def test_dev_gated_mock_and_test_example_vendor_paths_are_exempt(tmp_path: Path) -> None:
    write_source(
        tmp_path,
        "server/dev.mjs",
        """if (process.env.SCOPEWEAVE_DEV === '1') {\n  return { url: '/?billing=mock', mock: true }; // cwl-stub-scan: allow dev-only\n}\n""",
    )
    write_source(tmp_path, "tests/fake.ts", "throw new Error('Not implemented');\n")
    write_source(tmp_path, "examples/demo.go", 'package demo\nfunc x(){panic("TODO")}\n')
    write_source(tmp_path, "vendor/lib.java", 'throw new UnsupportedOperationException("TODO");\n')

    findings, errors = scan.scan_changed_paths(
        tmp_path,
        [
            Path("server/dev.mjs"),
            Path("tests/fake.ts"),
            Path("examples/demo.go"),
            Path("vendor/lib.java"),
        ],
    )

    assert findings == []
    assert errors == []


def test_tracked_paths_use_nul_delimited_git_inventory(tmp_path: Path) -> None:
    write_source(tmp_path, "src/a.py", "def ok():\n    return 1\n")
    write_source(tmp_path, "server/b.js", "export const ok = true;\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "src/a.py", "server/b.js"], cwd=tmp_path, check=True)

    assert scan.tracked_runtime_paths(tmp_path) == [
        Path("server/b.js"),
        Path("src/a.py"),
    ]


def test_tracked_inventory_has_a_bounded_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed instead of occupying a fleet runner until the job timeout."""
    calls: list[dict[str, object]] = []

    def timeout_run(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(kwargs)
        raise subprocess.TimeoutExpired(cmd="git ls-files", timeout=kwargs["timeout"])

    monkeypatch.setattr(scan.subprocess, "run", timeout_run)

    with pytest.raises(RuntimeError, match="Git inventory timed out"):
        scan.tracked_runtime_paths(tmp_path)
    assert calls == [
        {
            "check": True,
            "capture_output": True,
            "timeout": scan.GIT_INVENTORY_TIMEOUT_SECONDS,
        }
    ]


def test_oversized_runtime_source_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Record bounded evidence without loading an oversized source file."""
    relative_path = Path("src/oversized.js")
    write_source(tmp_path, relative_path.as_posix(), "x" * 17)
    monkeypatch.setattr(scan, "MAX_RUNTIME_FILE_BYTES", 16)

    findings, errors = scan.scan_changed_paths(tmp_path, [relative_path])

    assert findings == []
    assert errors == ["src/oversized.js exceeds the 16 byte scan limit"]


def test_uppercase_python_and_rust_suffixes_use_language_scanners(tmp_path: Path) -> None:
    """Dispatch every suffix accepted by the case-insensitive inventory filter."""
    write_source(tmp_path, "src/service.PY", "def pending():\n    pass\n")
    write_source(tmp_path, "src/provider.RS", "fn provider() { todo!() }\n")

    findings, errors = scan.scan_changed_paths(
        tmp_path, [Path("src/service.PY"), Path("src/provider.RS")]
    )

    assert errors == []
    assert [(item.path, item.line) for item in findings] == [
        ("src/provider.RS", 1),
        ("src/service.PY", 1),
    ]


def test_changed_file_inventory_delegates_to_the_central_parser(tmp_path: Path) -> None:
    """Preserve the central changed-file parser as the single parsing authority."""
    changed_file = tmp_path / "changed-files.txt"
    changed_file.write_text("src/a.py\nserver/b.js\n", encoding="utf-8")

    assert scan.changed_paths_from_file(changed_file) == [
        Path("src/a.py"),
        Path("server/b.js"),
    ]


def test_scan_skips_duplicates_non_runtime_and_missing_paths(tmp_path: Path) -> None:
    """Count each existing runtime source once and ignore non-runtime inventory."""
    write_source(tmp_path, "src/ok.py", "def ok():\n    return 1\n")

    findings, errors = scan.scan_changed_paths(
        tmp_path,
        [
            Path("src/ok.py"),
            Path("src/ok.py"),
            Path("README.md"),
            Path("src/missing.py"),
        ],
    )

    assert findings == []
    assert errors == []


def test_python_parse_errors_and_rust_findings_are_sorted(tmp_path: Path) -> None:
    """Report Python parser evidence while retaining Rust scanner findings."""
    write_source(tmp_path, "src/broken.py", "def broken(:\n    pass\n")
    write_source(tmp_path, "src/provider.rs", "fn provider() { todo!() }\n")

    findings, errors = scan.scan_changed_paths(
        tmp_path, [Path("src/provider.rs"), Path("src/broken.py")]
    )

    assert errors == ["src/broken.py:1 could not be parsed: invalid syntax"]
    assert [(item.path, item.line) for item in findings] == [("src/provider.rs", 1)]


def test_markdown_reports_cover_failure_and_clean_inventory() -> None:
    """Render deterministic human evidence for both failing and clean scans."""
    finding = scan.Finding("src/app.js", 4, "runtime", "explicit runtime stub marker")

    failed = scan.render_report([finding], ["src/broken.py:1 parse error"], 2)
    clean = scan.render_report([], [], 0)

    assert "- Result: FAIL" in failed
    assert "Parse errors:" in failed
    assert "src/broken.py:1 parse error" in failed
    assert "Findings:" in failed
    assert "src/app.js:4 `runtime` - explicit runtime stub marker" in failed
    assert clean.endswith("No executable or explicit runtime stubs were found.\n")


def test_json_report_is_deterministic_and_machine_readable() -> None:
    findings = [
        scan.Finding("z.js", 8, "runtime", "explicit runtime stub marker"),
        scan.Finding("a.py", 2, "sync", "pass-only body"),
    ]

    rendered = scan.render_json_report(findings, [], checked_count=3)
    payload = json.loads(rendered)

    assert payload["schema"] == "cwl.implementation-completeness/v2"
    assert payload["result"] == "fail"
    assert [item["path"] for item in payload["findings"]] == ["a.py", "z.js"]
    assert payload["repository"] is None
    assert payload["repository_sha"] is None
    assert payload["workflow_sha"] is None
    assert rendered.endswith("\n")

    bound = json.loads(
        scan.render_json_report(
            findings,
            [],
            checked_count=3,
            repository="ContextualWisdomLab/.github",
            repository_sha="a" * 40,
            workflow_sha="b" * 40,
        )
    )
    assert bound["repository"] == "ContextualWisdomLab/.github"
    assert bound["repository_sha"] == "a" * 40
    assert bound["workflow_sha"] == "b" * 40


def test_cli_requires_exactly_one_inventory_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["scan", "--repo-root", str(tmp_path)])
    with pytest.raises(SystemExit) as exc:
        scan.main()
    assert exc.value.code == 2


def test_cli_scans_all_tracked_sources_as_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Bind the all-tracked CLI path to JSON evidence and a successful exit."""
    runtime_path = write_source(tmp_path, "src/ok.py", "def ok():\n    return 1\n")
    monkeypatch.setattr(
        scan,
        "tracked_runtime_paths",
        lambda _root: [runtime_path.relative_to(tmp_path)],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["scan", "--repo-root", str(tmp_path), "--all-tracked", "--format", "json"],
    )

    assert scan.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"] == "pass"
    assert payload["checked_runtime_source_files"] == 1


def test_cli_filters_changed_files_and_returns_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Filter changed inventory before emitting Markdown failure evidence."""
    write_source(tmp_path, "src/stub.js", "throw new Error('Not implemented');\n")
    write_source(tmp_path, "docs/ignored.py", "def ignored():\n    pass\n")
    changed_file = tmp_path / "changed-files.txt"
    changed_file.write_text(
        "src/stub.js\nsrc/stub.js\ndocs/ignored.py\nsrc/missing.py\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "scan",
            "--repo-root",
            str(tmp_path),
            "--changed-files",
            str(changed_file),
        ],
    )

    assert scan.main() == 1
    output = capsys.readouterr().out
    assert "- Checked runtime source files: 1" in output
    assert "- Result: FAIL" in output


def test_parameterless_not_implemented_exception_fails(tmp_path: Path) -> None:
    """Inventory the idiomatic empty-argument implementation exception."""
    relative_path = Path("src/Service.cs")
    write_source(tmp_path, relative_path.as_posix(), "throw new NotImplementedException();\n")

    findings, errors = scan.scan_changed_paths(tmp_path, [relative_path])

    assert errors == []
    assert [(item.path, item.line, item.reason) for item in findings] == [
        (
            relative_path.as_posix(),
            1,
            "throws an explicit not-implemented exception",
        )
    ]


def test_require_commit_sha_and_repository_name_reject_unbound_identities() -> None:
    """Keep inventory provenance fail-closed when identity fields are malformed."""
    assert scan.require_commit_sha("A" * 40, "--repository-sha") == "a" * 40
    assert (
        scan.require_repository_name("ContextualWisdomLab/naruon")
        == "ContextualWisdomLab/naruon"
    )
    with pytest.raises(ValueError, match="40-character commit SHA"):
        scan.require_commit_sha("not-a-sha", "--repository-sha")
    with pytest.raises(ValueError, match="40-character commit SHA"):
        scan.require_commit_sha("g" * 40, "--workflow-sha")
    for bad in ("naruon", "a/b/c", "/naruon", "org/", ""):
        with pytest.raises(ValueError, match="owner/name"):
            scan.require_repository_name(bad)


def test_inventory_payload_binding_and_clean_gates() -> None:
    """Close a remediation issue only after a valid empty v2 inventory."""
    clean = {
        "schema": "cwl.implementation-completeness/v2",
        "result": "pass",
        "findings": [],
        "errors": [],
        "checked_runtime_source_files": 0,
    }
    assert scan.inventory_payload_is_binding(clean)
    assert scan.inventory_payload_is_clean(clean)
    assert not scan.inventory_payload_is_binding([])
    assert not scan.inventory_payload_is_binding({**clean, "schema": "other"})
    assert not scan.inventory_payload_is_binding({**clean, "result": "ok"})
    assert not scan.inventory_payload_is_binding({**clean, "findings": {}})
    assert not scan.inventory_payload_is_binding({**clean, "errors": {}})
    assert not scan.inventory_payload_is_binding(
        {**clean, "checked_runtime_source_files": "1"}
    )
    dirty = {**clean, "result": "fail", "findings": [{"path": "a.js"}]}
    assert scan.inventory_payload_is_binding(dirty)
    assert not scan.inventory_payload_is_clean(dirty)
    assert not scan.inventory_payload_is_clean({**clean, "errors": ["x"]})


def test_inventory_payload_identity_gate_binds_all_revisions() -> None:
    """Reject valid-looking inventories emitted for a different target or scanner."""
    clean = {
        "schema": "cwl.implementation-completeness/v2",
        "result": "pass",
        "findings": [],
        "errors": [],
        "checked_runtime_source_files": 0,
        "repository": "ContextualWisdomLab/naruon",
        "repository_sha": "a" * 40,
        "workflow_sha": "b" * 40,
    }

    assert scan.inventory_payload_matches_identity(
        clean,
        "ContextualWisdomLab/naruon",
        "a" * 40,
        "b" * 40,
    )
    assert not scan.inventory_payload_matches_identity(
        {**clean, "repository_sha": "c" * 40},
        "ContextualWisdomLab/naruon",
        "a" * 40,
        "b" * 40,
    )


def test_cli_binds_exact_repository_and_workflow_shas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Write repository and scanner revision identity into every JSON inventory."""
    runtime_path = write_source(tmp_path, "src/ok.py", "def ok():\n    return 1\n")
    monkeypatch.setattr(
        scan,
        "tracked_runtime_paths",
        lambda _root: [runtime_path.relative_to(tmp_path)],
    )
    repository_sha = "a" * 40
    workflow_sha = "b" * 40
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "scan",
            "--repo-root",
            str(tmp_path),
            "--all-tracked",
            "--format",
            "json",
            "--repository",
            "ContextualWisdomLab/.github",
            "--repository-sha",
            repository_sha,
            "--workflow-sha",
            workflow_sha,
        ],
    )

    assert scan.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["repository"] == "ContextualWisdomLab/.github"
    assert payload["repository_sha"] == repository_sha
    assert payload["workflow_sha"] == workflow_sha


def test_cli_rejects_a_malformed_repository_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refuse to emit an inventory whose commit identity cannot be bound."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "scan",
            "--repo-root",
            str(tmp_path),
            "--all-tracked",
            "--repository-sha",
            "not-a-sha",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        scan.main()
    assert exc.value.code == 2


def test_cli_changed_files_rejects_a_symlink_without_following(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Keep the changed-file inventory on the same fail-closed symlink path."""
    outside_source = tmp_path.parent / f"{tmp_path.name}-outside.py"
    outside_source.write_text("def outside():\n    return 1\n", encoding="utf-8")
    source_path = tmp_path / "src" / "service.py"
    source_path.parent.mkdir(parents=True)
    source_path.symlink_to(outside_source)
    changed_file = tmp_path / "changed-files.txt"
    changed_file.write_text("src/service.py\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "scan",
            "--repo-root",
            str(tmp_path),
            "--changed-files",
            str(changed_file),
        ],
    )

    assert scan.main() == 1
    assert "src/service.py is a symbolic link and cannot be scanned" in capsys.readouterr().out
