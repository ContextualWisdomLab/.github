"""Head locks may recombine base-pinned records without trusting head manifests."""

import json
import subprocess
import os
import pathlib
import textwrap

import pytest

from scripts.ci import materialize_base_rust_dependencies as materializer
from tests.test_materialize_base_rust_dependencies import _init_repo, _commit_all

REGISTRY = "registry+https://github.com/rust-lang/crates.io-index"


@pytest.mark.parametrize("change", ["lock", "source", "manifest", "rename-manifest"])
def test_workflow_opts_into_head_locks_only_with_unchanged_manifests(tmp_path, change):
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "Cargo.toml").write_text("base manifest\n")
    (repo / "Cargo.lock").write_text("base lock\n")
    base = _commit_all(repo)
    if change != "source":
        (repo / "Cargo.lock").write_text("repaired lock\n")
    if change == "source":
        (repo / "source.rs").write_text("source change\n")
    if change == "manifest":
        (repo / "Cargo.toml").write_text("changed manifest\n")
    if change == "rename-manifest":
        (repo / "Cargo.toml").rename(repo / "renamed.txt")
    head = _commit_all(repo)
    workflow = (
        pathlib.Path(__file__).resolve().parents[1]
        / ".github/workflows/opencode-review-dispatch.yml"
    ).read_text()
    start = workflow.index("            rust_lock_args=()")
    end = workflow.index('            cat >"$coverage_build_dir/Dockerfile"', start)
    block = textwrap.dedent(workflow[start:end])
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "python3"
    fake.write_text('#!/bin/bash\nprintf "%s\\0" "$@" >"$ARGUMENT_RECEIPT"\n')
    fake.chmod(0o755)
    receipt = tmp_path / "arguments"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "COVERAGE_SOURCE_WORKDIR": str(repo),
        "PR_BASE_SHA": base,
        "PR_HEAD_SHA": head,
        "GITHUB_WORKSPACE": str(tmp_path),
        "coverage_build_dir": str(tmp_path),
        "ARGUMENT_RECEIPT": str(receipt),
    }
    subprocess.run(
        ["bash", "-euo", "pipefail"],
        input=block,
        text=True,
        env=env,
        check=True,
        capture_output=True,
    )
    arguments = receipt.read_bytes().decode().split("\0")[:-1]
    assert ("--head-sha" in arguments) == (change == "lock")
    if change == "lock":
        assert arguments[arguments.index("--head-sha") + 1] == head
    assert arguments[arguments.index("--base-sha") + 1] == base


def lock(packages):
    text = "version = 4\n"
    for package in packages:
        text += "\n[[package]]\n"
        text += "".join(
            f"{key} = {json.dumps(value)}\n" for key, value in package.items()
        )
    return text


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "checksum",
        "version",
        "git-source",
        "manifest",
        "manifest-symlink",
        "missing-lock",
        "new-lock",
        "edge",
        "missing-edge",
        "duplicate",
        "unknown-field",
        "vendor-failure",
    ],
)
def test_head_intake_keeps_base_inputs_and_rejects_untrusted_changes(
    tmp_path, monkeypatch, mutation
):
    repo = tmp_path / "repo"
    _init_repo(repo)
    manifest = '[package]\nname="local"\nversion="1.0.0"\n[workspace]\n'
    (repo / "Cargo.toml").write_text(manifest)
    (repo / "fuzz").mkdir()
    (repo / "fuzz/Cargo.toml").write_text(
        '[package]\nname="fuzz"\nversion="0.0.0"\n[workspace]\n'
    )
    registry = {
        "name": "itoa",
        "version": "1.0.0",
        "source": REGISTRY,
        "checksum": "a" * 64,
    }
    other = {
        "name": "other",
        "version": "1.0.0",
        "source": REGISTRY,
        "checksum": "b" * 64,
    }
    local = {"name": "local", "version": "1.0.0", "dependencies": ["itoa"]}
    fuzz = {"name": "fuzz", "version": "0.0.0", "dependencies": ["local"]}
    (repo / "Cargo.lock").write_text(lock([local, registry, other]))
    (repo / "fuzz/Cargo.lock").write_text(lock([{"name": "fuzz", "version": "0.0.0"}]))
    base = _commit_all(repo)
    rows = [fuzz, local, dict(registry), dict(other)]
    if mutation == "checksum":
        rows[2]["checksum"] = "0" * 64
    if mutation == "version":
        rows[2]["version"] = "2.0.0"
        rows[1]["dependencies"] = ["itoa 2.0.0"]
    if mutation == "git-source":
        rows[2]["source"] = "git+https://example.invalid/repo#" + "c" * 40
    if mutation == "edge":
        rows[2]["dependencies"] = ["other"]
    if mutation == "missing-edge":
        rows[2]["dependencies"] = ["absent"]
    if mutation == "duplicate":
        rows.append(dict(registry))
    if mutation == "unknown-field":
        rows[2]["replace"] = "other"
    (repo / "fuzz/Cargo.lock").write_text(lock(rows))
    if mutation == "manifest":
        (repo / "Cargo.toml").write_text(manifest + "# changed\n")
    if mutation == "manifest-symlink":
        (repo / "extra").mkdir()
        (repo / "extra/Cargo.toml").symlink_to("../Cargo.toml")
    if mutation == "missing-lock":
        (repo / "fuzz/Cargo.lock").unlink()
    if mutation == "new-lock":
        (repo / "extra.lock/Cargo.lock").parent.mkdir()
        (repo / "extra.lock/Cargo.lock").write_text(lock(rows))
    head = _commit_all(repo)
    calls = []

    def vendor(path, output, sync):
        calls.append(path)
        assert path.read_text() == manifest
        assert (sync[0].parent / "Cargo.lock").read_text() == lock(rows)
        output.mkdir()
        return subprocess.CompletedProcess(
            [],
            1 if mutation == "vendor-failure" else 0,
            b'[source.vendored-sources]\ndirectory="vendor"\n',
            b"resolution failed",
        )

    monkeypatch.setattr(materializer, "_run_cargo_vendor", vendor)
    output = tmp_path / "output"
    if mutation is not None:
        with pytest.raises((ValueError, RuntimeError)):
            materializer.materialize(repo, base, output, head_sha=head)
        assert bool(calls) == (mutation == "vendor-failure")
        assert not (output / "manifest.json").exists()
    else:
        assert materializer.materialize(repo, base, output, head_sha=head) == [
            "Cargo.lock",
            "fuzz/Cargo.lock",
        ]
        receipt = json.loads((output / "lock-provenance.json").read_text())
        assert receipt["manifest_revision"] == base
        assert receipt["lock_revision"] == head
        assert receipt["locks"][1]["path"] == "fuzz/Cargo.lock"
        assert len(receipt["locks"][1]["lock_blob"]) == 40
