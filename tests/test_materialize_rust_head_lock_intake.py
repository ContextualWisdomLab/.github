"""Head locks may recombine base-pinned records without trusting head manifests."""

import json
import subprocess

import pytest

from scripts.ci import materialize_base_rust_dependencies as materializer
from tests.test_materialize_base_rust_dependencies import _init_repo, _commit_all

REGISTRY = "registry+https://github.com/rust-lang/crates.io-index"


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
