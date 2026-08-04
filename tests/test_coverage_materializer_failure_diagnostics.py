from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType
from typing import Callable

import pytest

from scripts.ci import materialize_base_javascript_packages as javascript_materializer
from scripts.ci import materialize_base_python_requirements as python_materializer


def _failing_materializer(error: BaseException) -> Callable[..., None]:
    """Return a materializer stub that raises the supplied failure."""

    def fail(*_args: object, **_kwargs: object) -> None:
        raise error

    return fail


def _run_main(module: ModuleType, tmp_path: Path) -> int:
    """Invoke one materializer CLI with a valid-shaped isolated argument set."""
    return module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--base-sha",
            "a" * 40,
            "--output-dir",
            str(tmp_path / "output"),
        ]
    )


def test_javascript_failure_publishes_exact_coverage_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deterministic review receives the exact early npm-lock failure."""
    output_file = tmp_path / "github-output"
    exact_reason = (
        "current-head npm lock package-lock.json package "
        "apps/desktop/node_modules/@types/react-dom must pin a registry "
        "tarball and SHA-512 integrity"
    )
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.setattr(
        javascript_materializer,
        "materialize",
        _failing_materializer(ValueError(exact_reason)),
    )

    assert _run_main(javascript_materializer, tmp_path) == 1

    published = output_file.read_text(encoding="utf-8")
    assert "coverage_summary<<CWL_COVERAGE_SUMMARY_EOF" in published
    assert "## Coverage Decision" in published
    assert "- Result: FAIL" in published
    assert "- Failed stage: Base JavaScript package lock materialization" in published
    assert f"ValueError: {exact_reason}" in published
    assert "rerun the current-head coverage-evidence job" in published


def test_python_failure_publishes_sanitized_bounded_coverage_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Early Python-lock failures remain concrete without output-file injection."""
    output_file = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.setattr(
        python_materializer,
        "materialize",
        _failing_materializer(
            OSError(
                "fixture <unsafe>\nCWL_COVERAGE_SUMMARY_EOF " + ("x" * 5000)
            )
        ),
    )

    assert _run_main(python_materializer, tmp_path) == 1

    published = output_file.read_text(encoding="utf-8")
    assert "- Failed stage: Base Python lock materialization" in published
    assert "OSError: fixture &lt;unsafe&gt; CWL_COVERAGE_SUMMARY_END" in published
    assert "<unsafe>" not in published
    assert published.count("CWL_COVERAGE_SUMMARY_EOF\n") == 2
    assert len(published) < 5000


@pytest.mark.parametrize(
    "module",
    [javascript_materializer, python_materializer],
    ids=["javascript", "python"],
)
def test_failure_diagnostics_are_optional_outside_github_actions(
    module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local CLI failures keep their status when no Actions output file exists."""
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setattr(
        module,
        "materialize",
        _failing_materializer(RuntimeError("local fixture failure")),
    )

    assert _run_main(module, tmp_path) == 1
    assert not (tmp_path / "github-output").exists()


def test_javascript_tree_filter_continues_after_non_regular_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Symlinks and gitlinks cannot hide later regular lock inputs."""
    tree_output = (
        b"120000 blob " + (b"1" * 40) + b"\tsymlinked-lock\0"
        b"160000 commit " + (b"2" * 40) + b"\tvendored-module\0"
        b"100644 blob " + (b"3" * 40) + b"\tpackage.json\0"
    )
    monkeypatch.setattr(
        javascript_materializer,
        "_git",
        lambda *_args: tree_output,
    )

    assert javascript_materializer._regular_base_paths(tmp_path, "a" * 40) == {
        "package.json"
    }


def test_npm_project_without_packages_map_keeps_root_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy npm locks without a packages map still preserve trusted root inputs."""
    regular_paths = {"package.json", "package-lock.json"}
    lock_content = json.dumps({"name": "legacy", "lockfileVersion": 1}).encode()
    monkeypatch.setattr(
        javascript_materializer,
        "_regular_base_paths",
        lambda *_args: regular_paths,
    )

    def fake_git(_repo_root: Path, _command: str, object_spec: str) -> bytes:
        if object_spec.endswith(":package.json"):
            return b'{"name":"legacy"}'
        if object_spec.endswith(":package-lock.json"):
            return lock_content
        raise AssertionError(f"unexpected git object: {object_spec}")

    monkeypatch.setattr(javascript_materializer, "_git", fake_git)

    projects = javascript_materializer.base_npm_projects(tmp_path, "a" * 40)

    assert projects == [
        (
            "package-lock.json",
            "npm",
            {
                "package.json": b'{"name":"legacy"}',
                "package-lock.json": lock_content,
            },
        )
    ]


def test_npm_workspace_scan_iterates_missing_and_regular_manifests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing workspace manifests are skipped without hiding later regular ones."""
    regular_paths = {
        "package.json",
        "package-lock.json",
        "packages/alpha/package.json",
        "packages/beta/package.json",
    }
    lock_content = json.dumps(
        {
            "name": "workspace-root",
            "lockfileVersion": 3,
            "packages": {
                "": {"name": "workspace-root"},
                "packages/aaa-missing": {"name": "missing"},
                "packages/alpha": {"name": "alpha"},
                "packages/beta": {"name": "beta"},
            },
        }
    ).encode()
    blobs = {
        "package.json": b'{"name":"workspace-root"}',
        "package-lock.json": lock_content,
        "packages/alpha/package.json": b'{"name":"alpha"}',
        "packages/beta/package.json": b'{"name":"beta"}',
    }
    monkeypatch.setattr(
        javascript_materializer,
        "_regular_base_paths",
        lambda *_args: regular_paths,
    )

    def fake_git(_repo_root: Path, _command: str, object_spec: str) -> bytes:
        return blobs[object_spec.split(":", 1)[1]]

    monkeypatch.setattr(javascript_materializer, "_git", fake_git)

    projects = javascript_materializer.base_npm_projects(tmp_path, "a" * 40)

    assert len(projects) == 1
    assert "packages/aaa-missing/package.json" not in projects[0][2]
    assert projects[0][2]["packages/alpha/package.json"] == b'{"name":"alpha"}'
    assert projects[0][2]["packages/beta/package.json"] == b'{"name":"beta"}'
