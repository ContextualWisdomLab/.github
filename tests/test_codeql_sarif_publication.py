"""Offline real HTTP-adapter/CLI controls for direct CodeQL SARIF custody."""
from __future__ import annotations

import base64
import copy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ci/codeql_sarif_publication.py"


def module():
    """Load the exact trusted helper without a network actor."""
    spec = importlib.util.spec_from_file_location("publication", SCRIPT)
    assert spec is not None and spec.loader is not None
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def identity():
    """Synthetic admitted metadata, never an actual GitHub run."""
    return dict(repository="ContextualWisdomLab/.github", pr_number="42",
                base_sha="a" * 40, head_sha="b" * 40, language="python",
                workflow_sha="c" * 40, run_id="100", run_attempt="1")


class Actor:
    """Finite supported REST responses; every unexpected request fails."""
    def __init__(self, status=None, analysis=None):
        self.calls = []
        self.status = status or {"processing_status": "complete"}
        self.analysis = analysis or dict(id=17, sarif_id="upload-1", ref="refs/pull/42/head",
            commit_sha="b" * 40, category="/language:python", analysis_key="API",
            tool={"name": "CodeQL", "version": "2.0"}, error="", warning="")

    def __call__(self, method, path, *, payload=None, accept="application/vnd.github+json"):
        self.calls.append((method, path, payload, accept))
        if method == "POST":
            assert path == "repos/ContextualWisdomLab/.github/code-scanning/sarifs"
            assert set(payload) == {"commit_sha", "ref", "sarif", "tool_name", "checkout_uri", "validate"}
            assert payload["commit_sha"] == "b" * 40
            assert payload["ref"] == "refs/pull/42/head"
            data = json.loads(gzip.decompress(base64.b64decode(payload["sarif"])))
            assert data["runs"][0]["automationDetails"]["id"] == "/language:python/"
            return {"id": "upload-1", "url": "https://api.github.com/repos/ContextualWisdomLab/.github/code-scanning/sarifs/upload-1"}
        if path.endswith("/sarifs/upload-1"):
            return copy.deepcopy(self.status)
        if "analyses?sarif_id=upload-1" in path:
            return [copy.deepcopy(self.analysis)]
        if path.endswith("/analyses/17"):
            if accept == "application/sarif+json":
                return {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "CodeQL"}}, "results": []}]}
            return copy.deepcopy(self.analysis)
        raise AssertionError((method, path))


def publish(tmp_path, actor=None, content=None, **changes):
    """Exercise the production publisher with synthetic external HTTP only."""
    m = module()
    source = tmp_path / "sarif"
    source.mkdir()
    raw = json.dumps(content or {"version": "2.1.0", "runs": [{
        "tool": {"driver": {"name": "CodeQL", "rules": []}}, "results": []}]}).encode()
    (source / "python.sarif").write_bytes(raw)
    args = identity() | changes
    receipt = m.publish(source, tmp_path / "custody", args, api=actor or Actor(),
                        checkout_uri=tmp_path.as_uri() + "/", sleeper=lambda _: None)
    return receipt, raw


def test_supported_post_processing_identity_and_durable_bytes(tmp_path):
    actor = Actor()
    receipt, raw = publish(tmp_path, actor)
    assert receipt["schema"] == "cwl-codeql-sarif-v1"
    assert receipt["state"] == "complete"
    assert receipt["identity"] == identity()
    record = receipt["uploads"][0]
    assert record["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert record["sarif_id"] == "upload-1"
    assert record["analysis_id"] == 17
    assert (tmp_path / "custody" / "source-0.sarif").read_bytes() == raw
    assert json.loads((tmp_path / "custody" / "receipt.json").read_text()) == receipt
    assert sum(c[0] == "POST" for c in actor.calls) == 1


@pytest.mark.parametrize("status", [
    {"processing_status": "failed", "errors": ["secret diagnostic"]},
    {"processing_status": "complete", "errors": ["partial processing"]},
    {"processing_status": "pending"}, {"processing_status": "mystery"}, {},
])
def test_processing_unknown_failure_partial_and_deadline_fail_closed(tmp_path, status):
    actor = Actor(status=status)
    actor.status = status
    with pytest.raises(RuntimeError):
        publish(tmp_path, actor)
    receipt = json.loads((tmp_path / "custody" / "receipt.json").read_text())
    assert receipt["state"] != "complete"
    assert "secret diagnostic" not in json.dumps(receipt)
    assert sum(c[0] == "POST" for c in actor.calls) == 1


@pytest.mark.parametrize("field,value", [
    ("commit_sha", "d" * 40), ("ref", "refs/heads/feature"),
    ("category", "/language:actions"), ("sarif_id", "another-upload"),
    ("error", "failed"), ("warning", "truncated"), ("id", True),
    ("tool", {"name": "Other"}), ("analysis_key", ""),
])
def test_analysis_readback_exact_identity_and_no_partial_acceptance(tmp_path, field, value):
    actor = Actor()
    actor.analysis[field] = value
    with pytest.raises(RuntimeError):
        publish(tmp_path, actor)
    assert json.loads((tmp_path / "custody" / "receipt.json").read_text())["state"] != "complete"


@pytest.mark.parametrize("details", [{"id": "/language:actions/"}, {"id": "/language:python/unreviewed"}])
def test_existing_conflicting_category_not_silently_overwritten(tmp_path, details):
    actor = Actor()
    with pytest.raises(RuntimeError):
        publish(tmp_path, actor, content={"version": "2.1.0", "runs": [{
            "tool": {"driver": {"name": "CodeQL"}}, "automationDetails": details, "results": []}]})
    assert not actor.calls


def test_http_adapter_canonical_authority_no_redirect_and_no_retry(monkeypatch):
    m = module()
    calls = []
    class Response:
        """Actual Request boundary observer."""
        status = 202
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def read(self, *_): return b'{"id":"upload-1"}'
    def open_request(request, **kwargs):
        calls.append(request)
        return Response()
    monkeypatch.setattr(m.OPENER, "open", open_request)
    api = m.GitHubAPI("synthetic-token")
    assert api("POST", "repos/ContextualWisdomLab/.github/code-scanning/sarifs", payload={}) == {"id": "upload-1"}
    assert calls[0].full_url.startswith("https://api.github.com/repos/")
    assert json.loads(calls[0].data) == {}
    with pytest.raises(RuntimeError): api("GET", "https://attacker.invalid/token")
    assert len(calls) == 1
    assert m.RejectRedirects().redirect_request(None, None, 302, "", {}, "https://attacker.invalid") is None


def test_receipt_log_verifier_rechecks_upload_and_exact_analysis(tmp_path):
    m = module()
    receipt, _ = publish(tmp_path)
    log = "2026-10-26T00:00:00Z " + m.receipt_line(receipt) + "\n"
    result = m.verify_log(log, identity(), api=Actor())
    assert result == receipt
    for field, value in [("head_sha", "d" * 40), ("run_id", "101"), ("run_attempt", "2"), ("language", "actions"), ("workflow_sha", "e" * 40)]:
        with pytest.raises(RuntimeError): m.verify_log(log, identity() | {field: value}, api=Actor())
    with pytest.raises(RuntimeError): m.verify_log(log + log, identity(), api=Actor())
    with pytest.raises(RuntimeError): m.verify_log(log, identity(), api=Actor(status={"processing_status": "failed"}))


def test_no_post_replay_after_ambiguous_transport(tmp_path):
    actor = Actor()
    def fail(method, path, **kwargs):
        actor.calls.append((method, path))
        raise RuntimeError("synthetic lost acknowledgement")
    with pytest.raises(RuntimeError): publish(tmp_path, fail)
    assert len(actor.calls) == 1
    assert (tmp_path / "custody" / "source-0.sarif").is_file()
    assert (tmp_path / "custody" / "receipt.json").is_file()


def test_workflow_wires_real_publication_before_identity_without_artifact_quota():
    text = (ROOT / ".github/workflows/codeql-scan-dispatch.yml").read_text()
    scan = text.split("  scan:\n", 1)[1].split("  settle-required-run:", 1)[0]
    assert "security-events: write" in scan
    assert "permission-security-events: write" in scan
    assert "permission-security-events: read" in scan
    assert "Publish and verify CodeQL SARIF in target code scanning" in scan
    assert scan.index("Publish and verify CodeQL SARIF in target code scanning") < scan.index("Verify GHAS base/head CodeQL configuration identity")
    assert "actions/upload-artifact@" not in scan
    assert "--identity-env" in scan
    assert "python3 -I" in scan
    settle = text.split("  settle-required-run:", 1)[1]
    assert "/artifacts?" not in settle
    assert "verify-log" in settle
    assert "codeql_sarif_publication.py" in settle


@pytest.mark.parametrize("name", ["source-0.sarif", "upload-0.sarif", "processed-0.sarif"])
def test_custody_rehash_rejects_changed_original_upload_or_subset(tmp_path, name):
    receipt, _ = publish(tmp_path)
    m = module()
    assert m.verify_custody(tmp_path / "custody", identity(), api=Actor()) == receipt
    (tmp_path / "custody" / name).write_bytes(b"changed")
    with pytest.raises(RuntimeError):
        m.verify_custody(tmp_path / "custody", identity(), api=Actor())


def test_existing_custody_blocks_post_replay(tmp_path):
    publish(tmp_path)
    actor = Actor()
    with pytest.raises(FileExistsError):
        module().publish(tmp_path / "sarif", tmp_path / "custody", identity(), api=actor,
                         checkout_uri=tmp_path.as_uri() + "/")
    assert not actor.calls


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":1e999}', 'not-json'])
def test_malformed_duplicate_and_nonfinite_evidence_rejected(raw):
    with pytest.raises(RuntimeError): module().load_json(raw)


def test_missing_permission_retains_original_without_network(tmp_path, monkeypatch):
    m = module()
    monkeypatch.setattr(m.OPENER, "open", lambda *_args, **_kw: pytest.fail("network forbidden"))
    with pytest.raises(RuntimeError): publish(tmp_path, m.GitHubAPI(""))
    assert (tmp_path / "custody" / "source-0.sarif").is_file()
    assert json.loads((tmp_path / "custody" / "receipt.json").read_text())["state"] == "incomplete-no-replay"


def test_real_cli_custody_and_log_paths(tmp_path, monkeypatch, capsys):
    m = module()
    receipt, _ = publish(tmp_path)
    monkeypatch.setattr(m, "GitHubAPI", lambda _token: Actor())
    for key, value in identity().items(): monkeypatch.setenv(key.upper(), value)
    monkeypatch.setenv("GH_TOKEN", "synthetic-token")
    assert m.main(["verify-custody", "--identity-env", "--custody", str(tmp_path / "custody")]) == 0
    log = tmp_path / "job.log"
    log.write_text(m.receipt_line(receipt))
    assert m.main(["verify-log", "--identity-env", "--log", str(log)]) == 0
    monkeypatch.setenv("HEAD_SHA", "d" * 40)
    assert m.main(["verify-log", "--identity-env", "--log", str(log)]) == 1
    assert "synthetic-token" not in capsys.readouterr().err


@pytest.mark.parametrize("change", [
    {"extra": "x"}, {"run_id": 1}, {"repository": "Other/repo"},
    {"repository": "ContextualWisdomLab/.."}, {"head_sha": "invalid"},
    {"run_attempt": "0"}, {"language": "unknown"},
])
def test_identity_rejects_malformed_before_io(change):
    with pytest.raises(RuntimeError): module().validate_identity(identity() | change)


def test_finite_json_and_preexisting_exact_category_remain_supported():
    m = module()
    assert m.load_json('{"finite":1.5}') == {"finite": 1.5}
    data = {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "CodeQL"}},
            "automationDetails": {"id": "/language:python/"}}]}
    assert json.loads(m.prepare(json.dumps(data), identity())) == data


@pytest.mark.parametrize("data", [[], {"version": "2.1.0", "runs": []},
    {"version": "2.1.0", "runs": [None]},
    {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "Other"}}}]}])
def test_invalid_sarif_structure_is_not_uploaded(data):
    with pytest.raises(RuntimeError): module().prepare(json.dumps(data), identity())


def test_malformed_analysis_row_rejected():
    with pytest.raises(RuntimeError): module().check_analysis(None, identity(), "upload-1")


def test_source_uri_and_custody_symlink_refusals(tmp_path):
    m = module()
    with pytest.raises(RuntimeError):
        m.publish(tmp_path, tmp_path / "custody", identity(), api=Actor(), checkout_uri=tmp_path.as_uri())
    source = tmp_path / "sarif"
    source.mkdir()
    (source / "test.sarif").write_text('{}')
    with pytest.raises(RuntimeError):
        m.publish(source, tmp_path / "custody", identity(), api=Actor(), checkout_uri="https://attacker.invalid")
    target = tmp_path / "actual"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(RuntimeError):
        m.publish(source, link / "custody", identity(), api=Actor(), checkout_uri=tmp_path.as_uri())


@pytest.mark.parametrize("fault", ["ack", "rows", "changed", "subset"])
def test_ambiguous_or_incomplete_readbacks_retain_original(tmp_path, fault):
    m = module()
    actor = Actor()
    def api(method, path, **kwargs):
        data = actor(method, path, **kwargs)
        if fault == "ack" and method == "POST": return {"id": "../bad"}
        if fault == "rows" and "?sarif_id=" in path: return []
        if fault == "changed" and path.endswith("/analyses/17"): return data | {"new_field": True}
        if fault == "subset" and kwargs.get("accept") == "application/sarif+json": return {}
        return data
    with pytest.raises(RuntimeError): publish(tmp_path, api)
    assert (tmp_path / "custody" / "source-0.sarif").is_file()


@pytest.mark.parametrize("field,value", [("source_sha256", "not-a-hash"),
    ("sarif_id", "../bad"), ("analysis_id", False), ("analysis_key", "different")])
def test_receipt_references_and_digests_cannot_be_forged(tmp_path, field, value):
    receipt, _ = publish(tmp_path)
    receipt["uploads"][0][field] = value
    with pytest.raises(RuntimeError): module().verify_log(module().receipt_line(receipt), identity(), api=Actor())


def test_nonreceipt_log_lines_are_not_claims(tmp_path):
    receipt, _ = publish(tmp_path)
    m = module()
    assert m.verify_log("ordinary log\n" + m.receipt_line(receipt), identity(), api=Actor()) == receipt


@pytest.mark.parametrize("failure", ["status", "link", "size", "http", "transport"])
def test_http_refusal_bounds_close_and_sanitized_diagnostics(monkeypatch, failure):
    import io
    import urllib.error
    m = module()
    closed = []
    class Body(io.BytesIO):
        def close(self):
            closed.append(True)
            super().close()
    class Response:
        status = 200
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def read(self, *_): return b'{}'
    response = Response()
    if failure == "status": response.status = 201
    if failure == "link": response.headers = {"Link": "untrusted next"}
    if failure == "size": monkeypatch.setattr(m, "MAX_RESPONSE", 1)
    def open_request(*_args, **_kwargs):
        if failure == "http": raise urllib.error.HTTPError("https://api.github.com", 403, "secret", {}, Body(b"secret"))
        if failure == "transport": raise urllib.error.URLError("secret")
        return response
    monkeypatch.setattr(m.OPENER, "open", open_request)
    with pytest.raises(RuntimeError) as exc:
        m.GitHubAPI("synthetic-token")("GET", "repos/ContextualWisdomLab/.github/code-scanning/analyses/17")
    assert "secret" not in str(exc.value)
    if failure == "http": assert closed


def test_cli_publish_summary_and_missing_arguments(tmp_path, monkeypatch, capsys):
    m = module()
    monkeypatch.setattr(m, "GitHubAPI", lambda _token: Actor())
    for key, value in identity().items(): monkeypatch.setenv(key.upper(), value)
    source = tmp_path / "sarif"
    source.mkdir()
    (source / "python.sarif").write_text(json.dumps({"version": "2.1.0", "runs": [
        {"tool": {"driver": {"name": "CodeQL"}}, "results": []}]}))
    summary = tmp_path / "summary"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert m.main(["publish", "--identity-env", "--source", str(source), "--custody", str(tmp_path / "custody")]) == 0
    assert m.PREFIX in capsys.readouterr().out
    assert "upload-1" in summary.read_text()
    monkeypatch.delenv("GITHUB_STEP_SUMMARY")
    assert m.main(["publish", "--identity-env", "--source", str(source), "--custody", str(tmp_path / "second")]) == 0
    for mode in ("publish", "verify-custody", "verify-log"):
        assert m.main([mode, "--identity-env"]) == 1


def test_real_isolated_entrypoint_missing_permission_exits_one(tmp_path):
    import os
    import subprocess
    import sys
    process = subprocess.run([sys.executable, "-I", str(SCRIPT), "verify-log", "--identity-env"],
        env={"PATH": os.environ["PATH"], "TMPDIR": str(tmp_path)}, capture_output=True, text=True)
    assert process.returncode == 1
    assert "publication/custody incomplete" in process.stderr


def test_native_main_guard_is_executed_in_process(monkeypatch):
    import runpy
    import sys
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "verify-log", "--identity-env"])
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert result.value.code == 1


def observe_publication_fsync(m, monkeypatch, root, failure=None):
    """Observe real descriptor fsyncs; inject only an explicit IO error, no crash."""
    import os
    import stat
    real_open, real_fsync, real_close = os.open, os.fsync, os.close
    names, directory_fds, successes, faults = {}, set(), [], []
    phase = None

    def open_file(path, flags, *args, **kwargs):
        fd = real_open(path, flags, *args, **kwargs)
        names[fd] = Path(path).absolute()
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directory_fds.add(fd)
        return fd

    def sync(fd):
        nonlocal phase
        path = names[fd]
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            event = ("directory", path, phase if path == root else "namespace")
        else:
            phase = (json.loads(path.read_bytes())["state"] if path.name == "receipt.json"
                     else path.name)
            event = ("file", path, phase)
        if event == failure:
            faults.append(event)
            raise OSError("synthetic-fsync-private-diagnostic")
        real_fsync(fd)
        successes.append(event)

    def close(fd):
        real_close(fd)
        directory_fds.discard(fd)

    monkeypatch.setattr(m.os, "open", open_file)
    monkeypatch.setattr(m.os, "fsync", sync)
    monkeypatch.setattr(m.os, "close", close)
    return successes, faults, directory_fds


def namespace_case(tmp_path, existing_depth):
    """Create only the fixture's admitted anchor; remaining names belong to publish."""
    source = tmp_path / "input"
    source.mkdir()
    raw = json.dumps({"version": "2.1.0", "runs": [
        {"tool": {"driver": {"name": "CodeQL", "rules": []}}, "results": []}]}).encode()
    (source / "python.sarif").write_bytes(raw)
    ancestors = [tmp_path, tmp_path / "persistent", tmp_path / "persistent/100",
                 tmp_path / "persistent/100/1"]
    ancestors[existing_depth].mkdir(parents=True, exist_ok=True)
    root = ancestors[-1] / "python"
    return source, root, raw, list(reversed(ancestors[existing_depth:]))


@pytest.mark.parametrize("existing_depth", [0, 1, 3], ids=["new", "partial", "existing"])
def test_custody_namespace_entries_and_original_intent_fsynced_before_post(tmp_path, monkeypatch, existing_depth):
    m = module()
    source, root, raw, required = namespace_case(tmp_path, existing_depth)
    successes, faults, directory_fds = observe_publication_fsync(m, monkeypatch, root)
    actor, snapshot = Actor(), []

    def api(method, path, **kwargs):
        if method == "POST":
            snapshot.extend(successes)
        return actor(method, path, **kwargs)

    receipt = m.publish(source, root, identity(), api=api, checkout_uri=tmp_path.as_uri() + "/")
    assert sum(c[0] == "POST" for c in actor.calls) == 1
    for parent in required:
        event = ("directory", parent, "namespace")
        assert event in snapshot, "POST without durable custody namespace entry"
        assert snapshot.index(event) < snapshot.index(("file", root / "receipt.json", "post-intent"))
    for name, phase in (("source-0.sarif", "source-0.sarif"), ("receipt.json", "prepared"),
                        ("upload-0.sarif", "upload-0.sarif"), ("receipt.json", "post-intent")):
        file_event, leaf_event = ("file", root / name, phase), ("directory", root, phase)
        assert file_event in snapshot and leaf_event in snapshot
        assert snapshot.index(file_event) < snapshot.index(leaf_event)
    assert (root / "source-0.sarif").read_bytes() == raw
    assert receipt["state"] == "complete"
    assert not faults and not directory_fds


FSYNC_FAULTS = [(depth, "namespace", index) for depth in (0, 3) for index in range(4 - depth)]
FSYNC_FAULTS += [(depth, kind, phase) for depth in (0, 3) for kind in ("file", "leaf")
                 for phase in ("source-0.sarif", "prepared", "upload-0.sarif", "post-intent")]


@pytest.mark.parametrize("existing_depth,kind,stage", FSYNC_FAULTS)
def test_prepost_fsync_error_zero_post_fixed_diagnostic_and_no_replay(tmp_path, monkeypatch, capsys,
                                                                    existing_depth, kind, stage):
    m = module()
    source, root, raw, required = namespace_case(tmp_path, existing_depth)
    if kind == "namespace":
        failure = ("directory", required[stage], "namespace")
    elif kind == "leaf":
        failure = ("directory", root, stage)
    else:
        name = "receipt.json" if stage in {"prepared", "post-intent"} else stage
        failure = ("file", root / name, stage)
    actor = Actor()
    monkeypatch.setattr(m, "GitHubAPI", lambda _: actor)
    for key, value in identity().items():
        monkeypatch.setenv(key.upper(), value)
    with monkeypatch.context() as io_patch:
        _successes, faults, directory_fds = observe_publication_fsync(m, io_patch, root, failure)
        assert m.main(["publish", "--identity-env", "--source", str(source), "--custody", str(root)]) == 1
    assert faults == [failure], "fault site must actually be exercised"
    assert not actor.calls and not directory_fds
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "::error::CodeQL SARIF publication/custody incomplete; no success or replay authorized.\n"
    assert root.is_dir()
    if (root / "source-0.sarif").exists():
        assert (root / "source-0.sarif").read_bytes() == raw
    if (root / "receipt.json").exists():
        assert json.loads((root / "receipt.json").read_bytes())["state"] != "complete"
    # Retry only after removing the injected error; retain the real exclusive-root fence.
    with pytest.raises(FileExistsError):
        m.publish(source, root, identity(), api=actor, checkout_uri=tmp_path.as_uri() + "/")
    assert not actor.calls
