"""Close the release dependency gate's remaining fail-closed branch gaps."""

from __future__ import annotations

import hashlib
import importlib
import json
import runpy
import subprocess
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts.ci import release_dependency_gate as gate
from tests.test_release_dependency_fanout_plan import CONTROL, _allowed
from tests.test_release_dependency_gate import CRATE_HASH, _write, build_capture


def _commit(source: Path, message: str = "fixture") -> str:
    """Commit the complete fixture and return its exact Git identity."""

    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--allow-empty",
            "-qm",
            message,
        ],
        cwd=source,
        check=True,
    )
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, text=True
    ).strip()


def test_python_310_toml_fallback_loads_the_declared_compatibility_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Python 3.10 runtime without ``tomllib`` must use the declared fallback."""

    real_import_module = importlib.import_module
    fallback = SimpleNamespace(loads=tomllib.loads)

    def import_without_tomllib(name: str, package: str | None = None) -> Any:
        if name == "tomllib":
            raise ModuleNotFoundError("simulated Python 3.10")
        if name == "tomli":
            return fallback
        return real_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", import_without_tomllib)
    namespace = runpy.run_path(str(Path(gate.__file__)))
    assert namespace["tomllib"] is fallback


def test_benign_rust_build_script_has_no_process_or_network_finding() -> None:
    """A Rust build script without a process/network namespace remains admissible."""

    assert gate.detect_install_hooks({"build.rs": "fn main() { println!(\"cargo:rerun\"); }"}) == []


@pytest.mark.parametrize(
    ("name", "target", "leg", "member", "expected_kind"),
    [
        ("libc.so.6", "manylinux_2_28_x86_64", "linux-py3.13", "pkg/core.so", "system-runtime"),
        ("libunknown.so", "manylinux_2_28_x86_64", "linux-py3.13", "pkg/core.so", None),
        (
            "@rpath/fast_mlsirm._core.cpython-313-darwin.so",
            "macosx_11_0_x86_64-darwin",
            "darwin-py3.13",
            "fast_mlsirm/_core.cpython-313-darwin.so",
            "self-install-name",
        ),
        ("PYTHON313.DLL", "win_amd64-windows", "windows-py3.13", "pkg/core.pyd", "interpreter-runtime"),
        ("UNKNOWN.DLL", "win_amd64-windows", "windows-py3.13", "pkg/core.pyd", None),
        ("libc.so.6", "freebsd_14_x86_64", "freebsd-py3.13", "pkg/core.so", None),
    ],
)
def test_platform_link_classifier_distinguishes_reviewed_and_unknown_runtime_links(
    name: str,
    target: str,
    leg: str,
    member: str,
    expected_kind: str | None,
) -> None:
    """Only the target-specific runtime identities receive an allowlisted basis."""

    result = gate.classify_platform_link(name, target, leg, member)
    assert (result and result["kind"]) == expected_kind


def test_selection_capture_cli_accepts_an_exact_commit_without_a_selection_file(
    tmp_path: Path,
) -> None:
    """An absent optional selection file is a successful, empty capture via the CLI."""

    source = tmp_path / "source"
    source.mkdir()
    sha = _commit(source)
    capture = tmp_path / "capture"
    assert gate.main(
        [
            "capture-license-selections",
            "--source",
            str(source),
            "--source-sha",
            sha,
            "--capture",
            str(capture),
        ]
    ) == 0
    assert not capture.exists()


def test_selection_capture_requires_an_exact_commit_sha(tmp_path: Path) -> None:
    """A branch-like selection identity is rejected before any Git object lookup."""

    with pytest.raises(gate.GateError, match="exact commit SHA"):
        gate.capture_license_selections(tmp_path, "main", tmp_path / "capture")


def test_selection_capture_rejects_a_symlink_git_object(tmp_path: Path) -> None:
    """A committed symlink cannot stand in for the regular selection JSON blob."""

    source = tmp_path / "source"
    path = source / "docs" / "release-license-selections.json"
    path.parent.mkdir(parents=True)
    path.symlink_to("elsewhere.json")
    sha = _commit(source)
    with pytest.raises(gate.GateError, match="regular Git blob"):
        gate.capture_license_selections(source, sha, tmp_path / "capture")


def test_selection_capture_rechecks_the_blob_size_after_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Git returning more bytes than its size metadata cannot bypass the read bound."""

    source = tmp_path / "source"
    path = source / "docs" / "release-license-selections.json"
    path.parent.mkdir(parents=True)
    path.write_text("[]", encoding="utf-8")
    sha = _commit(source)
    real_check_output = gate.subprocess.check_output

    def inconsistent_git(command: list[str], **kwargs: Any) -> Any:
        if command[1:3] == ["cat-file", "-s"]:
            return b"1\n"
        if command[1:3] == ["cat-file", "blob"]:
            return b"oversized"
        return real_check_output(command, **kwargs)

    monkeypatch.setattr(gate.subprocess, "check_output", inconsistent_git)
    monkeypatch.setattr(gate, "_MAX_METADATA_BYTES", 2)
    with pytest.raises(gate.GateError, match="bounded size"):
        gate.capture_license_selections(source, sha, tmp_path / "capture")


def _source_bound_cargo_capture(
    tmp_path: Path, *, workspace_version: bool = False
) -> tuple[Path, Path, str]:
    """Build a small source-bound Cargo capture backed by real Git objects."""

    capture = build_capture(tmp_path / "capture")
    source = (tmp_path / "source").resolve()
    wheel = source / "crates" / "wheel"
    core = source / "crates" / "core" / "Cargo.toml"
    wheel.mkdir(parents=True)
    core.parent.mkdir(parents=True)
    core.write_text(
        '[package]\nname = "local-core"\n'
        + ('version.workspace = true\n' if workspace_version else 'version = "1.0.0"\n'),
        encoding="utf-8",
    )
    wheel_manifest = '[package]\nname = "fast-mlsirm"\nversion = "0.11.5"\n'
    if workspace_version:
        wheel_manifest += '\n[workspace.package]\nversion = "1.0.0"\n'
    (wheel / "Cargo.toml").write_text(wheel_manifest, encoding="utf-8")
    lock = capture / "cargo" / "Cargo.lock"
    lock.write_text(
        lock.read_text(encoding="utf-8")
        + '\n[[package]]\nname = "local-core"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    (wheel / "Cargo.lock").write_bytes(lock.read_bytes())
    sha = _commit(source)

    metadata_path = capture / "cargo" / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["workspace_root"] = str(wheel)
    metadata["packages"][0]["manifest_path"] = str(wheel / "Cargo.toml")
    metadata["packages"].append(
        {
            "id": "local-id",
            "name": "local-core",
            "version": "1.0.0",
            "source": None,
            "manifest_path": str(core),
        }
    )
    metadata["resolve"]["nodes"][0]["deps"].append({"pkg": "local-id"})
    metadata["resolve"]["nodes"].append(
        {"id": "local-id", "deps": [{"pkg": "greencrate-id"}]}
    )
    _write(metadata_path, metadata)
    return capture, source, sha


def test_cargo_source_binding_rejects_a_nonexact_commit(tmp_path: Path) -> None:
    """Source-bound Cargo declarations require a full immutable commit identity."""

    capture, source, _sha = _source_bound_cargo_capture(tmp_path)
    with pytest.raises(gate.GateError, match="source checkout cannot be bound"):
        gate._enumerate_cargo(capture, source_root=source, source_sha="main")


def test_cargo_workspace_must_be_inside_the_selected_source(tmp_path: Path) -> None:
    """Absolute Cargo metadata still fails when its workspace escapes the checkout."""

    capture, source, sha = _source_bound_cargo_capture(tmp_path)
    metadata_path = capture / "cargo" / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["workspace_root"] = str((tmp_path / "outside").resolve())
    _write(metadata_path, metadata)
    with pytest.raises(gate.GateError, match="source checkout cannot be bound"):
        gate._enumerate_cargo(capture, source_root=source, source_sha=sha)


def test_cargo_workspace_inherited_version_is_bound_to_the_root_manifest(
    tmp_path: Path,
) -> None:
    """A path crate's inherited version must resolve from committed workspace bytes."""

    capture, source, sha = _source_bound_cargo_capture(tmp_path, workspace_version=True)
    dependencies, failures, expected = gate._enumerate_cargo(
        capture, source_root=source, source_sha=sha
    )
    assert failures == []
    assert {dependency.key for dependency in dependencies} == expected == {
        "cargo/greencrate@0.1.0"
    }


@pytest.mark.parametrize("matches_source", [False, True])
def test_development_cargo_lock_must_match_the_committed_root_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    matches_source: bool,
) -> None:
    """A distinct development graph is admitted only with the exact root lock bytes."""

    capture = build_capture(tmp_path / "capture")
    source = tmp_path / "source"
    source.mkdir()
    root_lock = (capture / "cargo" / "Cargo.lock").read_bytes() + b"# development graph\n"
    (source / "Cargo.lock").write_bytes(root_lock)
    sha = _commit(source)
    release = json.loads((capture / "release.json").read_text(encoding="utf-8"))
    release["source_sha"] = sha
    _write(capture / "release.json", release)
    dev = capture / "cargo-dev"
    dev.mkdir()
    (dev / "Cargo.lock").write_bytes(root_lock if matches_source else b"other lock")
    dependency = gate.Dependency(
        "cargo", "greencrate", "0.1.0", frozenset({CRATE_HASH})
    )

    def enumerate_cargo(*_args: Any, **_kwargs: Any) -> tuple[list[gate.Dependency], list[gate.Failure], set[str]]:
        return [dependency], [], {dependency.key}

    monkeypatch.setattr(gate, "_enumerate_cargo", enumerate_cargo)
    if not matches_source:
        with pytest.raises(gate.GateError, match="development Cargo lock differs"):
            gate.gate(capture, stage=gate.LICENSE_STAGE, source_root=source)
        return
    report = gate.gate(capture, stage=gate.LICENSE_STAGE, source_root=source)
    assert report.passed


def _source_notice_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> tuple[Path, str, str, dict[str, str], dict[str, Any]]:
    """Create one reviewed supplemental notice declaration in a real Git tree."""

    source = tmp_path / "source"
    notice_path = "python/fast_mlsirm/_licenses/example-1.0.0.txt"
    first, second = b"MIT", b"Apache"
    content = first + (b"--" if mutation == "separator" else b"\n\n") + second
    digest = hashlib.sha256(content).hexdigest()
    first_digest = "0" * 64 if mutation == "grant" else hashlib.sha256(first).hexdigest()
    grants = (
        ("LICENSE-MIT", len(first), first_digest),
        ("LICENSE-APACHE", len(second), hashlib.sha256(second).hexdigest()),
    )
    archive_sha = "a" * 64
    upstream_commit = "b" * 40
    repository = "example/project"
    upstream = [
        {
            "url": f"https://raw.githubusercontent.com/{repository}/{upstream_commit}/{name}",
            "sha256": sha,
        }
        for name, _size, sha in grants
    ]
    selection = {
        "chosen": "MIT AND Apache-2.0",
        "rationale": "Retain both immutable grants.",
    }
    choice = {
        "ecosystem": "cargo",
        "name": "example",
        "version": "1.0.0",
        **selection,
        "archive_sha256": archive_sha,
        "bundled_notice": {"path": notice_path, "sha256": digest},
        "upstream_licenses": upstream,
    }
    choices: Any = [choice]
    if mutation == "object":
        choices = {"choice": choice}
    elif mutation == "missing-choice":
        choices = []
    _write(source / "docs" / "release-license-selections.json", choices)
    notice = source / notice_path
    notice.parent.mkdir(parents=True)
    notice.write_bytes(content)
    sha = _commit(source)
    monkeypatch.setitem(
        gate._REVIEWED_SOURCE_NOTICES,
        "cargo/example@1.0.0",
        (
            archive_sha,
            repository,
            upstream_commit,
            digest,
            {"MIT AND Apache-2.0"},
            grants,
        ),
    )
    evidence = {"ecosystem": "cargo", "source_sha256": archive_sha}
    return source, sha, notice_path, selection, evidence


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("bad-sha", "exact release commit"),
        ("oversized", "bounded size"),
        ("object", "JSON array"),
        ("missing-choice", "one explicit notice selection"),
        ("separator", "separator differs"),
        ("grant", "grant bytes differ"),
    ],
)
def test_source_notice_refuses_each_unbound_git_or_grant_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    message: str,
) -> None:
    """Every reviewed source notice remains bound to exact Git and grant bytes."""

    source, sha, _notice_path, selection, evidence = _source_notice_fixture(
        tmp_path, monkeypatch, mutation
    )
    if mutation == "bad-sha":
        sha = "main"
    elif mutation == "oversized":
        monkeypatch.setattr(gate, "_MAX_METADATA_BYTES", 1)
    with pytest.raises(gate.GateError, match=message):
        gate._source_license_notice(
            source, sha, "cargo/example@1.0.0", evidence, selection
        )


def _runtime_archive_row(ecosystem: str, name: str, digest_byte: str) -> dict[str, Any]:
    """Build one internally consistent runtime archive verdict row."""

    source_hash = digest_byte * 64
    key = f"{ecosystem}/{name}@1.0/sha256/{source_hash}"
    evidence = {
        "source_sha256": source_hash,
        "archive_members": [],
        "install_hook_sources": {},
        "parsed_inputs": [],
        "native_libraries": [],
        "known_vulnerabilities": [],
    }
    fixture = gate.build_fixture(gate.Dependency(ecosystem, name, "1.0"), evidence)
    fixture["id"] = key
    return {
        "key": key,
        "package_key": f"{ecosystem}/{name}@1.0",
        "name": name,
        "version": "1.0",
        "source_sha256": source_hash,
        "license": "MIT",
        "fixture": fixture,
        "fixture_sha256": gate.fixture_digest(fixture),
    }


def test_runtime_archives_cannot_expand_an_in_limit_plan_past_the_job_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Runtime archive rows are counted with base dependencies before fanout."""

    capture, report_path = _allowed(tmp_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    monkeypatch.setattr(gate, "STRIX_PLAN_LIMIT", len(report["dependencies"]))
    archive_report = tmp_path / "runtime.json"
    archive_report.write_text(
        json.dumps(
            {
                "schema": "cwl.release-runtime-archive-licenses/3",
                "archives": [_runtime_archive_row("pypi", "runtime", "a")],
                "build_packages": [_runtime_archive_row("pypi", "builder", "b")],
                "build_tools": [
                    _runtime_archive_row("github-release", "maturin", "c")
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(gate.GateError, match="plan exceeds"):
        gate.strix_fanout_plan(
            capture, report_path, CONTROL, 1, 1, archive_report
        )
