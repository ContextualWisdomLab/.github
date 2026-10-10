"""Exercise existing central fail-closed boundaries without commands or network."""

from __future__ import annotations

import copy
import hashlib
import json
from urllib.error import HTTPError, URLError
from io import BytesIO

import pytest

from scripts.ci import noema_review_gate as noema
from scripts.ci import release_dependency_gate as gate
from scripts.ci import prescreen_release_runtime_archives as prescreen
from scripts.ci import pingora_edge_policy as policy
from tests.test_release_dependency_gate import build_capture
from tests.test_release_dependency_fanout_plan import _allowed, CONTROL
from tests.test_verify_release_scope_evidence_set import _prescreen_case, _scope_with_variants


def test_content_envelope_malformed_json_is_refused(monkeypatch):
    """Malformed API JSON never reaches content decoding."""
    monkeypatch.setattr(noema, "run", lambda *args, **kwargs: "{not-json")
    with pytest.raises(RuntimeError, match="GitHub content response was malformed"):
        noema.fetch_file_content_at_ref("owner/repo", "docs/a.md", "deadbeef")


@pytest.mark.parametrize("kind", ["url", "timeout", "http"])
def test_raw_blob_transport_errors_are_sanitized(monkeypatch, kind):
    """Transport details are not leaked and the original cause is retained."""
    body = BytesIO(b"private response")
    if kind == "http":
        error = HTTPError("private url", 500, "private reason", {}, body)
    elif kind == "url":
        error = URLError("private dns")
    else:
        error = TimeoutError("private timeout")
    def fail(request, timeout):
        assert timeout == 30
        assert request.full_url.endswith("/git/blobs/" + "a" * 40)
        raise error
    monkeypatch.setattr(policy.github_opener, "open", fail)
    try:
        with pytest.raises(policy.PolicyError) as caught:
            policy._github_open_raw_bytes("https://api.github.com/repos/a/b/git/blobs/" + "a" * 40, "token", 4)
        assert str(caught.value) == f"GitHub raw blob request failed: {type(error).__name__}"
        assert caught.value.__cause__ is error
    finally:
        error.close() if isinstance(error, HTTPError) else body.close()


def test_inline_content_requires_string_payload():
    """An otherwise regular base64 envelope cannot carry a numeric payload."""
    payload = {"type": "file", "encoding": "base64", "size": 1, "content": 1}
    with pytest.raises(policy.PolicyError, match="malformed size or content field"):
        policy._load_raw_file_bytes("https://api.github.com", "a/b", "a.md", "head", "token", lambda *args: payload)


def test_inline_encoding_is_rechecked_at_decode_boundary():
    """A synthetic changing API field cannot bypass the second encoding guard."""
    class ChangingEncoding(str):
        def __ne__(self, other):
            return other == "base64"
    payload = {"type": "file", "encoding": ChangingEncoding("base64"), "size": 1, "content": "eA=="}
    with pytest.raises(policy.PolicyError, match="not a regular base64 file"):
        policy._load_raw_file_bytes("https://api.github.com", "a/b", "a.md", "head", "token", lambda *args: payload)
    payload["encoding"] = "base64"
    assert policy._load_raw_file_bytes("https://api.github.com", "a/b", "a.md", "head", "token", lambda *args: payload) == b"x"


@pytest.mark.parametrize("mutation", ["oversized", "changed", "architecture", "json"])
def test_runtime_receipt_prescreen_refuses_untrusted_bytes(tmp_path, mutation):
    """Receipt size, digest, JSON and interpreter identity are independent gates."""
    root, rows = _prescreen_case(tmp_path)
    scope = _scope_with_variants(rows, root)
    row = rows[0]
    path = root / row["artifact_name"] / f"{row['leg']}.runtime.json"
    if mutation == "oversized":
        path.write_bytes(b"x" * (1024 * 1024 + 1))
        message, code = "runtime receipt is oversized", gate.SCOPE_UNVERIFIABLE
    elif mutation == "changed":
        path.write_bytes(path.read_bytes() + b" ")
        message, code = "runtime receipt changed after transport", gate.SOURCE_HASH_MISMATCH
    else:
        runtime = json.loads(path.read_bytes())
        runtime["machine"] = "foreign"
        path.write_bytes(b"{bad-json" if mutation == "json" else json.dumps(runtime).encode())
        row["members"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        message, code = ("JSON" if mutation == "json" else "runtime interpreter differs"), gate.SCOPE_UNVERIFIABLE
    with pytest.raises(gate.GateError, match=message) as caught:
        prescreen.prescreen(scope, root)
    assert caught.value.code == code


def test_macos_build_receipt_requires_known_interpreter_architecture(tmp_path):
    """A hash-bound receipt still needs a recognized macOS interpreter suffix."""
    root, rows = _prescreen_case(tmp_path)
    row = next(row for row in rows if row["leg"].startswith("universal2"))
    folder = root / row["artifact_name"]
    path = folder / f"{row['leg']}.build-first.json"
    receipt = json.loads(path.read_bytes())
    receipt["build_env"] = "runner:macOS/UNKNOWN"
    path.write_text(json.dumps(receipt))
    with pytest.raises(gate.GateError, match="build interpreter architecture is missing") as caught:
        prescreen._build_packages(row, folder)
    assert caught.value.code == gate.SCOPE_UNVERIFIABLE


def test_runtime_prescreen_requires_sdist_after_complete_iteration(tmp_path, monkeypatch):
    """Thirteen valid runtime legs cannot replace the mandatory source leg."""
    root, rows = _prescreen_case(tmp_path)
    scope = _scope_with_variants(rows, root)
    sdist = rows[-1]
    replacement = copy.deepcopy(rows[0])
    replacement["leg"] = "x86_64-unknown-linux-gnu-py3.15"
    replacement["artifact_name"] = "repro-digest-" + replacement["leg"]
    folder = root / replacement["artifact_name"]
    folder.mkdir()
    original = root / rows[0]["artifact_name"]
    for archive in replacement["archives"]:
        (folder / archive["file"]).write_bytes((original / archive["file"]).read_bytes())
    runtime_name = replacement["leg"] + ".runtime.json"
    raw = b"{}"
    (folder / runtime_name).write_bytes(raw)
    replacement["members"][runtime_name] = hashlib.sha256(raw).hexdigest()
    rows[-1] = replacement
    monkeypatch.setattr(prescreen, "_runtime_target_architecture", lambda *args, **kwargs: "x86_64")
    monkeypatch.setattr(prescreen, "_build_packages", lambda *args: [])
    monkeypatch.setattr(prescreen, "_maturin_tool", lambda item, folder: {
        "key": "tool", "legs": [item["leg"]], "build_envs": {item["leg"]: "fixture"}})
    with pytest.raises(gate.GateError, match="runtime archive coverage is incomplete") as caught:
        prescreen.prescreen(scope, root)
    assert caught.value.code == gate.SCOPE_UNVERIFIABLE
    assert sdist["leg"] == "sdist"


def test_rust_build_hook_namespace_positive_and_negative():
    """Ordinary Rust build code is allowed but networking is detected."""
    assert gate.detect_install_hooks({"build.rs": 'fn main() { println!("cargo:rerun"); }'}) == []
    assert gate.detect_install_hooks({"build.rs": "use std::net; fn main() {}"}) == [
        "build.rs references a process/network namespace"]


@pytest.mark.parametrize("mutation", ["invalid-sha", "absent", "symlink", "raced", "valid"])
def test_selection_capture_binds_exact_regular_bounded_git_blob(tmp_path, monkeypatch, mutation):
    """Capture checks immutable metadata and actual payload before publication."""
    capture = tmp_path / "capture"
    commands = []
    def git(command, **kwargs):
        commands.append(command)
        assert kwargs["cwd"] == tmp_path
        if command[1] == "ls-tree":
            return "" if mutation == "absent" else f"{'120000' if mutation == 'symlink' else '100644'} blob oid\tdocs/release-license-selections.json"
        if command[2] == "-s":
            return b"2\n"
        assert command[2:] == ["blob", "oid"]
        return b"x" * (gate._MAX_METADATA_BYTES + 1) if mutation == "raced" else b"[]"
    monkeypatch.setattr(gate.subprocess, "check_output", git)
    sha = "short" if mutation == "invalid-sha" else "a" * 40
    if mutation in {"invalid-sha", "symlink", "raced"}:
        message = {"invalid-sha": "exact commit SHA", "symlink": "regular Git blob", "raced": "exceeds bounded size"}[mutation]
        with pytest.raises(gate.GateError, match=message):
            gate.capture_license_selections(tmp_path, sha, capture)
        assert not capture.exists()
    else:
        assert gate.main(["capture-license-selections", "--source", str(tmp_path), "--source-sha", sha, "--capture", str(capture)]) == 0
        if mutation == "valid":
            assert (capture / "license-selections.json").read_bytes() == b"[]"
        else:
            assert not capture.exists()
    if mutation == "invalid-sha":
        assert commands == []


@pytest.mark.parametrize("mutation", ["nonexact", "foreign-workspace", "workspace-version", "dev-match", "dev-mismatch"])
def test_cargo_checkout_and_development_graph_binding(tmp_path, monkeypatch, mutation):
    """Synthetic Git boundaries retain real source files, TOML and graph checking."""
    capture = build_capture(tmp_path / "capture")
    source = tmp_path / "source"
    wheel = source / "crates/wheel"
    core = source / "crates/core/Cargo.toml"
    wheel.mkdir(parents=True)
    core.parent.mkdir(parents=True)
    core.write_text('[package]\nname="local-core"\nversion="1.0.0"\n')
    (wheel / "Cargo.toml").write_text('[package]\nname="fast-mlsirm"\nversion="0.11.5"\n')
    lock = capture / "cargo/Cargo.lock"
    lock.write_text(lock.read_text() + '\n[[package]]\nname="local-core"\nversion="1.0.0"\n')
    (wheel / "Cargo.lock").write_bytes(lock.read_bytes())
    if mutation == "workspace-version":
        core.write_text('[package]\nname="local-core"\nversion.workspace=true\n')
        (wheel / "Cargo.toml").write_text((wheel / "Cargo.toml").read_text() + '[workspace.package]\nversion="1.0.0"\n')
    metadata_path = capture / "cargo/metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["workspace_root"] = str(tmp_path / "foreign" if mutation == "foreign-workspace" else wheel)
    metadata["packages"][0]["manifest_path"] = str(wheel / "Cargo.toml")
    metadata["packages"].append({"id": "local-id", "name": "local-core", "version": "1.0.0", "source": None, "manifest_path": str(core)})
    metadata["resolve"]["nodes"][0]["deps"].append({"pkg": "local-id"})
    metadata["resolve"]["nodes"].append({"id": "local-id", "deps": [{"pkg": "greencrate-id"}]})
    metadata_path.write_text(json.dumps(metadata))
    if mutation.startswith("dev-"):
        (source / "Cargo.lock").write_bytes(lock.read_bytes() + b"# development\n")
        dev = capture / "cargo-dev"
        dev.mkdir()
        (dev / "Cargo.lock").write_bytes((source / "Cargo.lock").read_bytes() if mutation == "dev-match" else b"different")
        dev_metadata = copy.deepcopy(metadata)
        dev_metadata["workspace_root"] = str(source)
        (dev / "metadata.json").write_text(json.dumps(dev_metadata))
    committed = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    def git(command, **kwargs):
        assert command[:3] == ["git", "-C", str(source)]
        if command[3:] == ["rev-parse", "--show-toplevel"]:
            return str(source) + "\n"
        if command[3:] == ["rev-parse", "HEAD"]:
            return "a" * 40 + "\n"
        if command[3] == "ls-tree":
            return b"100644 blob oid\tCargo.lock\n" if "Cargo.lock" in committed else b""
        assert command[3] == "show"
        return committed[command[4].split(":", 1)[1]]
    monkeypatch.setattr(gate.subprocess, "check_output", git)
    if mutation in {"nonexact", "foreign-workspace"}:
        with pytest.raises(gate.GateError, match="Cargo source checkout cannot be bound"):
            gate._enumerate_cargo(capture, source_root=source, source_sha="short" if mutation == "nonexact" else "a" * 40)
    elif mutation == "dev-mismatch":
        with pytest.raises(gate.GateError, match="development Cargo lock differs from source root"):
            gate.gate(capture, stage=gate.LICENSE_STAGE, source_root=source)
    elif mutation == "dev-match":
        assert gate.gate(capture, stage=gate.LICENSE_STAGE, source_root=source).passed
    else:
        dependencies, failures, expected = gate._enumerate_cargo(capture, source_root=source, source_sha="a" * 40)
        assert not failures
        assert {item.key for item in dependencies} == expected == {"cargo/greencrate@0.1.0"}


@pytest.mark.parametrize("mutation, message", [
    ("valid", None), ("nonexact", "exact release commit"),
    ("oversized", "blob exceeds bounded size"), ("not-list", "must be a JSON array"),
    ("missing-choice", "lacks one explicit notice selection"),
    ("separator", "grant separator differs"), ("grant", "grant bytes differ")])
def test_reviewed_source_notice_immutable_grant_boundaries(tmp_path, monkeypatch, mutation, message):
    """Owner-compatible synthetic grants check complete digest and per-grant binding."""
    subject, archive_sha, source_sha = "cargo/example@1.0.0", "a" * 64, "b" * 40
    first, second = b"MIT", b"BSD"
    content = (b"BAD" if mutation == "grant" else first) + (b"xx" if mutation == "separator" else b"\n\n") + second
    digest = hashlib.sha256(content).hexdigest()
    grants = (("LICENSE-MIT", 3, hashlib.sha256(first).hexdigest()), ("LICENSE-BSD", 3, hashlib.sha256(second).hexdigest()))
    monkeypatch.setitem(gate._REVIEWED_SOURCE_NOTICES, subject, (archive_sha, "owner/repo", "c" * 40, digest, {"MIT"}, grants))
    upstream = [{"url": f"https://raw.githubusercontent.com/owner/repo/{'c' * 40}/{name}", "sha256": sha} for name, _, sha in grants]
    selection = {"chosen": "MIT", "rationale": "Reviewed immutable grant bytes."}
    choice = {"ecosystem": "cargo", "name": "example", "version": "1.0.0", **selection, "archive_sha256": archive_sha, "upstream_licenses": upstream,
              "bundled_notice": {"path": "python/fast_mlsirm/_licenses/example.txt", "sha256": digest}}
    choices = b"{}" if mutation == "not-list" else json.dumps([] if mutation == "missing-choice" else [choice]).encode()
    def git(command, **kwargs):
        assert command[:3] == ["git", "-C", str(tmp_path)]
        if command[3] == "ls-tree":
            return f"100644 blob {'selection' if command[-1].endswith('.json') else 'notice'}\t{command[-1]}\n"
        if command[4] == "-s":
            return str(gate._MAX_METADATA_BYTES + 1 if mutation == "oversized" else 1).encode()
        assert command[4] == "blob"
        return choices if command[5] == "selection" else content
    monkeypatch.setattr(gate.subprocess, "check_output", git)
    args = (tmp_path, "short" if mutation == "nonexact" else source_sha, subject, {"ecosystem": "cargo", "source_sha256": archive_sha}, selection)
    if message:
        with pytest.raises(gate.GateError, match=message):
            gate._source_license_notice(*args)
    else:
        texts, bound = gate._source_license_notice(*args)
        assert list(texts.values()) == ["MIT", "BSD"]
        assert bound["source_sha"] == source_sha and bound["sha256"] == digest


def test_runtime_fixtures_cannot_push_fanout_past_512_jobs(tmp_path):
    """The post-runtime merge limit applies even to fully authenticated fixtures."""
    capture, report = _allowed(tmp_path / "capture")
    archives = []
    for index in range(513):
        sha = hashlib.sha256(str(index).encode()).hexdigest()
        key = f"pypi/example@1/sha256/{sha}"
        fixture = gate.build_fixture(gate.Dependency("pypi", "example", "1"), {"source_sha256": sha, "archive_members": [], "install_hook_sources": {}, "parsed_inputs": [], "native_libraries": [], "known_vulnerabilities": []})
        fixture["id"] = key
        archives.append({"key": key, "package_key": "pypi/example@1", "name": "example", "version": "1", "source_sha256": sha, "license": "MIT", "fixture": fixture, "fixture_sha256": gate.fixture_digest(fixture)})
    tool = archives[-1]
    tool["key"] = f"github-release/example@1/sha256/{tool['source_sha256']}"
    tool["package_key"] = "github-release/example@1"
    tool["fixture"]["id"] = tool["key"]
    tool["fixture"]["dependency"]["ecosystem"] = "github-release"
    tool["fixture_sha256"] = gate.fixture_digest(tool["fixture"])
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps({"schema": "cwl.release-runtime-archive-licenses/3", "archives": archives[:-2], "build_packages": [archives[-2]], "build_tools": [tool]}))
    with pytest.raises(gate.GateError, match="dependency plan exceeds 512 jobs") as caught:
        gate.strix_fanout_plan(capture, report, CONTROL, 42, 2, path)
    assert caught.value.code == gate.SCOPE_UNVERIFIABLE


@pytest.mark.parametrize("name,target,leg,member,kind", [
    ("libc.so.6", "x86_64-unknown-linux-gnu", "linux-py3.14", "module.so", "system-runtime"),
    ("@rpath/fast_mlsirm._core.so", "universal2-apple-darwin", "mac-py3.14", "fast_mlsirm/_core.so", "self-install-name"),
    ("python314.dll", "x86_64-pc-windows-msvc", "windows-py3.14", "module.pyd", "interpreter-runtime"),
    ("foreign.dll", "x86_64-pc-windows-msvc", "windows-py3.14", "module.pyd", None),
    ("foreign", "unknown-target", "unknown-py3.14", "module", None),
])
def test_platform_link_classification_controls(name, target, leg, member, kind):
    """Complete affected tests retain platform-specific positive and unknown controls."""
    result = gate.classify_platform_link(name, target, leg, member)
    if kind is None:
        assert result is None
    else:
        assert result["name"] == name and result["kind"] == kind
