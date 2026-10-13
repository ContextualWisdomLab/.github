"""Source-only admission tests; synthetic pins are never operational approval."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "ci" / "premerge_review_tooling.py"


def _load():
    """Require the actual controller boundary rather than a fixture substitute."""
    assert MODULE.is_file(), "missing trusted premerge tooling admission boundary"
    spec = importlib.util.spec_from_file_location("premerge_review_tooling", MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture():
    """Return inert source bytes and an independently supplied fixture digest."""
    files = {".github/actions/noema-review/two_phase.py": b"# FIXTURE ONLY\n"}
    manifest = {
        "schema_version": 1,
        "repository": "ContextualWisdomLab/.github",
        "commit": "a" * 40,
        "tree": "b" * 40,
        "entrypoint": ".github/actions/noema-review/two_phase.py",
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
    }
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return raw, files, hashlib.sha256(raw).hexdigest()


def test_unaccepted_tooling_rejected_before_source_consumption():
    """A caller cannot replace independent acceptance with its own digest."""
    module = _load()
    raw, files, _accepted = _fixture()
    with pytest.raises(ValueError, match="accepted manifest digest"):
        module.admit_tooling(raw, accepted_digest="0" * 64, source_files=files)


def test_source_inventory_must_equal_accepted_manifest():
    """Even a pinned manifest cannot admit substituted or extra executable bytes."""
    module = _load()
    raw, files, accepted = _fixture()
    for changed in [
        {next(iter(files)): b"# substituted\n"},
        {**files, "scripts/ci/hidden.py": b"# extra\n"},
        {},
    ]:
        with pytest.raises(ValueError, match="source inventory"):
            module.admit_tooling(raw, accepted_digest=accepted, source_files=changed)


def test_complete_pinned_source_inventory_admitted():
    """Nonempty exact source bytes have a useful positive admission control."""
    raw, files, accepted = _fixture()
    assert _load().admit_tooling(raw, accepted_digest=accepted, source_files=files) is None


@pytest.mark.parametrize("change", [
    {"schema_version": True},
    {"schema_version": 2},
    {"repository": "foreign/repo"},
    {"commit": "main"},
    {"tree": "b" * 39},
    {"entrypoint": "../outside.py"},
    {"entrypoint": "scripts/ci/not-listed.py"},
    {"unexpected": "field"},
    {"files": {}},
    {"files": {"../outside.py": "c" * 64}},
])
def test_pinned_but_invalid_manifest_refused(change):
    """Independent digest acceptance is necessary but does not replace schema checks."""
    module = _load()
    raw, files, _accepted = _fixture()
    manifest = {**json.loads(raw), **change}
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(ValueError, match="manifest"):
        module.admit_tooling(raw, accepted_digest=hashlib.sha256(raw).hexdigest(), source_files=files)


@pytest.mark.parametrize("name", ["/absolute.py", "a//b.py", "a/./b.py", "a/../b.py", "a\\b.py", "a\x00b.py"])
def test_noncanonical_inventory_path_refused(name):
    """Self-consistent unsafe paths cannot leave the immutable tooling namespace."""
    module = _load()
    raw, _files, _accepted = _fixture()
    manifest = json.loads(raw)
    files = {name: b"# inert\n"}
    manifest["files"] = {name: hashlib.sha256(files[name]).hexdigest()}
    manifest["entrypoint"] = name
    raw = json.dumps(manifest).encode()
    with pytest.raises(ValueError, match="manifest"):
        module.admit_tooling(raw, accepted_digest=hashlib.sha256(raw).hexdigest(), source_files=files)


def test_duplicate_manifest_field_refused():
    """Ambiguous authenticated JSON is not a second interpretation of an accepted source."""
    raw, files, _accepted = _fixture()
    raw = raw[:-1] + b',"schema_version":1}'
    with pytest.raises(ValueError, match="manifest"):
        _load().admit_tooling(raw, accepted_digest=hashlib.sha256(raw).hexdigest(), source_files=files)


@pytest.mark.parametrize("raw", [b"[]", b"null", b"{", b"{}" + b" " * (2 * 1024 * 1024)])
def test_malformed_or_oversized_pinned_manifest_refused(raw):
    """A trusted digest cannot make malformed or unbounded metadata usable."""
    with pytest.raises(ValueError, match="manifest"):
        _load().admit_tooling(raw, accepted_digest=hashlib.sha256(raw).hexdigest(), source_files={})


def _scope():
    """A fixture scope contains explicit reviewed PR and independent reviewer identities."""
    return {
        "repository": "ContextualWisdomLab/example", "number": 7,
        "head": "c" * 40, "base": "d" * 40,
        "author": "seonghobae", "reviewer": "cwl-noema-review[bot]",
    }


@pytest.mark.parametrize("change", [
    {"head": "e" * 40}, {"base": "e" * 40}, {"author": "other"},
    {"reviewer": "other[bot]"}, {"repository": "ContextualWisdomLab/other"},
    {"number": 8}, {"state": "CLOSED"}, {"draft": True},
])
def test_review_scope_drift_rejected(change):
    """Full live scope, not head alone, defines premerge evidence applicability."""
    module = _load()
    assert hasattr(module, "require_review_scope"), "missing full live review scope admission"
    live = {**_scope(), "state": "OPEN", "draft": False, **change}
    with pytest.raises(ValueError, match="review scope"):
        module.require_review_scope(_scope(), live)


def test_current_full_review_scope_allowed():
    """A live independently authored non-draft PR remains reviewable."""
    module = _load()
    assert hasattr(module, "require_review_scope"), "missing full live review scope admission"
    module.require_review_scope(_scope(), {**_scope(), "state": "OPEN", "draft": False})


@pytest.mark.parametrize("change", [
    {"number": True}, {"number": 0}, {"head": "main"}, {"base": "d" * 39},
    {"repository": "foreign/repo"}, {"author": ""}, {"reviewer": ""},
    {"reviewer": "seonghobae"}, {"reviewer": "SeongHoBae"},
])
def test_matching_invalid_or_self_review_scope_refused(change):
    """Equality cannot make malformed identity or self approval admissible."""
    scope = {**_scope(), **change}
    with pytest.raises(ValueError, match="review scope"):
        _load().require_review_scope(scope, {**scope, "state": "OPEN", "draft": False})


def test_controller_refuses_runtime_admission_before_loading_tooling(tmp_path):
    """A reviewed source pin never implies runner or supplier admission."""
    module = _load()
    assert hasattr(module, "run_review"), "missing executable premerge controller"
    raw, files, accepted = _fixture()
    events = []

    def admission():
        events.append("admission")
        raise RuntimeError("native/policy NOT_HELD")

    def load():
        pytest.fail("unadmitted tooling must not load")

    with pytest.raises(RuntimeError, match="NOT_HELD"):
        module.run_review(
            raw, accepted_digest=accepted, source_files=files, scope=_scope(),
            fetch_live=lambda: {**_scope(), "state": "OPEN", "draft": False},
            require_execution_admission=admission, load_tooling=load,
            refresh_publisher=lambda: pytest.fail("no credentials before admission"),
            private_parent=tmp_path,
        )
    assert events == ["admission"]
    assert not list(tmp_path.iterdir())


def test_controller_composes_actual_compatible_two_phase_modules(tmp_path, monkeypatch):
    """Real prepare/seal/read/publish runs with inert network/model collaborators only."""
    module = _load()
    two_path = ROOT / ".github/actions/noema-review/two_phase.py"
    spec = importlib.util.spec_from_file_location("trusted_two_phase_fixture", two_path)
    two = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(two)
    scope = _scope()
    pr = {"state": "OPEN", "isDraft": False, "headRefOid": scope["head"],
          "baseRefOid": scope["base"], "author": {"login": scope["author"]}}
    events = []
    monkeypatch.setattr(two.gate, "fetch_pr", lambda *_: pr)
    monkeypatch.setattr(two.gate, "current_actor", lambda: scope["reviewer"])
    monkeypatch.setattr(two.gate, "existing_noema_review", lambda *_: False)
    monkeypatch.setattr(two.gate, "fetch_diff", lambda *_: ("fixture diff", False))
    monkeypatch.setattr(two.gate, "fetch_changed_files", lambda *_: [("src/a.py", "MODIFIED")])
    monkeypatch.setattr(two.gate, "build_review_context", lambda *_: "fixture context")

    def model(*_):
        events.append("actual_prepare_model_boundary")
        return {"decision": "approve", "summary": "FIXTURE ONLY: not a real model verdict"}

    monkeypatch.setattr(two.gate, "call_llm", model)
    monkeypatch.setattr(two.gate, "submit_review", lambda *_: events.append("actual_publisher_sink"))

    def load():
        events.append("load_accepted_fixture_tooling")
        return two

    def refresh():
        events.append("independent_publisher_refresh_fixture")

    raw, files, accepted = _fixture()
    result = module.run_review(
        raw, accepted_digest=accepted, source_files=files, scope=scope,
        fetch_live=lambda: {**scope, "state": "OPEN", "draft": False},
        require_execution_admission=lambda: events.append("admission_fixture"),
        load_tooling=load, refresh_publisher=refresh, private_parent=tmp_path,
    )
    assert result == 0
    assert events == ["admission_fixture", "load_accepted_fixture_tooling",
                      "actual_prepare_model_boundary", "admission_fixture",
                      "independent_publisher_refresh_fixture", "actual_publisher_sink"]
    assert not list(tmp_path.iterdir())


def test_controller_rejects_forged_runner_local_envelope(tmp_path):
    """The controller never forwards a SOURCE_PASS or arbitrary envelope as model evidence."""
    from types import SimpleNamespace

    raw, files, accepted = _fixture()

    def prepare(_repo, _number, _head, path):
        path.write_text(json.dumps({"SOURCE_PASS": True}))
        return 0

    with pytest.raises(ValueError, match="prepared envelope"):
        _load().run_review(
            raw, accepted_digest=accepted, source_files=files, scope=_scope(),
            fetch_live=lambda: {**_scope(), "state": "OPEN", "draft": False},
            require_execution_admission=lambda: None,
            load_tooling=lambda: SimpleNamespace(prepare_verdict=prepare,
                publish_verdict=lambda *_: pytest.fail("must not publish")),
            refresh_publisher=lambda: pytest.fail("must not refresh"), private_parent=tmp_path,
        )
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("phase", ["missing", "failed", "scope_drift", "admission_revoked", "refresh_drift"])
def test_controller_rejects_unpublishable_preparation(tmp_path, phase):
    """No refresh or publication follows a missing verdict or expired scope/admission."""
    from types import SimpleNamespace

    module = _load()
    raw, files, accepted = _fixture()
    observations = 0
    admissions = 0
    refreshed = False

    def live():
        nonlocal observations
        observations += 1
        return {**_scope(), "state": "OPEN", "draft": False,
                **({"base": "e" * 40} if (phase == "scope_drift" and observations > 1) or refreshed else {})}

    def refresh():
        nonlocal refreshed
        if phase != "refresh_drift":
            pytest.fail("must not refresh")
        refreshed = True

    def admission():
        nonlocal admissions
        admissions += 1
        if phase == "admission_revoked" and admissions > 1:
            raise RuntimeError("admission revoked")

    def prepare(_repo, _number, _head, path):
        if phase != "missing":
            scope = _scope()
            payload = {
                "schema_version": 1, "repository": scope["repository"],
                "pull_request_number": scope["number"], "expected_head": scope["head"],
                "expected_base": scope["base"], "reviewer_actor": scope["reviewer"],
                "pull_request_author": scope["author"], "verdict": {"decision": "approve"},
            }
            path.write_text(json.dumps(payload))
            path.chmod(0o600)
        return 1 if phase == "failed" else 0

    with pytest.raises((RuntimeError, ValueError)):
        module.run_review(
            raw, accepted_digest=accepted, source_files=files, scope=_scope(),
            fetch_live=live, require_execution_admission=admission,
            load_tooling=lambda: SimpleNamespace(prepare_verdict=prepare,
                publish_verdict=lambda *_: pytest.fail("must not publish")),
            refresh_publisher=refresh, private_parent=tmp_path,
        )
    assert not list(tmp_path.iterdir())


def test_tooling_loader_rejects_mutated_source_before_child(tmp_path):
    """Live module bytes, not a retained mapping alone, are checked at spawn."""
    module = _load()
    assert hasattr(module, "load_noema_tooling"), "missing bound executable tooling loader"
    raw, files, accepted = _fixture()
    path = tmp_path / next(iter(files))
    path.parent.mkdir(parents=True)
    path.write_bytes(b"# substituted\n")
    with pytest.raises(ValueError, match="source inventory"):
        module.load_noema_tooling(
            tmp_path, raw, accepted_digest=accepted, interpreter=Path(__import__('sys').executable),
            phase_environment={}, child_runner=lambda *_args, **_kwargs: pytest.fail("must not spawn"),
        ).prepare_verdict("ContextualWisdomLab/example", 7, "c" * 40, tmp_path / "verdict.json")


@pytest.mark.parametrize("phase,environment", [
    ("publish", {"NOEMA_LLM_API_KEY": "SYNTHETIC_ONLY"}),
    ("prepare", {"NOEMA_LLM_MODEL": "orchestrator/free"}),
    ("prepare", {"NOEMA_LLM_MODEL": "auto", "PYTHONPATH": "/untrusted"}),
    ("prepare", {"NOEMA_LLM_MODEL": "auto", "LD_PRELOAD": "/untrusted"}),
])
def test_phase_environment_rejected_before_child(tmp_path, phase, environment):
    """Publisher gets no inference secret and model child gets no injection overrides."""
    import sys

    module = _load()
    raw, files, accepted = _fixture()
    for name, data in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    tooling = module.load_noema_tooling(
        tmp_path, raw, accepted_digest=accepted, interpreter=Path(sys.executable),
        phase_environment=lambda _: environment,
        child_runner=lambda *_args, **_kwargs: pytest.fail("forbidden environment reached child"),
    )
    with pytest.raises(ValueError, match="phase environment"):
        getattr(tooling, phase + "_verdict")("ContextualWisdomLab/example", 7, "c" * 40, tmp_path.parent / "unused.json")


def test_live_boolean_number_cannot_equal_admitted_integer():
    """Python equality must not treat a malformed live PR number as scope equality."""
    expected = {**_scope(), "number": 1}
    with pytest.raises(ValueError, match="review scope"):
        _load().require_review_scope(expected, {**expected, "number": True, "state": "OPEN", "draft": False})


def _token_response(phase):
    """Synthetic GitHub installation-token issuance response, never a live token."""
    return {"token": "SYNTHETIC_FIXTURE_ONLY",
            "permissions": {"contents": "read", "metadata": "read",
                            "pull_requests": "read" if phase == "prepare" else "write"},
            "repositories": [{"full_name": _scope()["repository"]}]}


@pytest.mark.parametrize("phase,change", [
    ("prepare", {"permissions": {"contents": "read", "pull_requests": "write"}}),
    ("prepare", {"permissions": {"contents": "write", "pull_requests": "read"}}),
    ("publish", {"permissions": {"contents": "read", "pull_requests": "read"}}),
    ("prepare", {"repositories": [{"full_name": "ContextualWisdomLab/other"}]}),
    ("prepare", {"repositories": [{"full_name": _scope()["repository"]}, {"full_name": "ContextualWisdomLab/other"}]}),
    ("prepare", {"token": ""}),
])
def test_issued_credential_scope_rejected_before_phase_environment(phase, change):
    """Trusted issuance response must prove exact phase permissions and repository."""
    module = _load()
    assert hasattr(module, "phase_environment_from_issuance"), "missing issuance-scoped consumer"
    response = {**_token_response(phase), **change}
    with pytest.raises(ValueError, match="credential issuance"):
        module.phase_environment_from_issuance(
            phase, response, scope=_scope(), reviewer_actor="cwl-noema-review[bot]",
            installation_id=7, inference_key="SYNTHETIC_INFERENCE_ONLY",
        )


@pytest.mark.parametrize("phase,response,actor,installation,key", [
    ("invalid", {}, "cwl-noema-review[bot]", 7, "SYNTHETIC"),
    ("prepare", None, "cwl-noema-review[bot]", 7, "SYNTHETIC"),
    ("prepare", _token_response("prepare"), "foreign[bot]", 7, "SYNTHETIC"),
    ("prepare", _token_response("prepare"), "cwl-noema-review[bot]", True, "SYNTHETIC"),
    ("prepare", _token_response("prepare"), "cwl-noema-review[bot]", 7, None),
])
def test_issuance_identity_and_inference_characterization(phase, response, actor, installation, key):
    """Unsupported or missing authenticated authority metadata remains a refusal."""
    with pytest.raises(ValueError, match="credential issuance"):
        _load().phase_environment_from_issuance(phase, response, scope=_scope(),
            reviewer_actor=actor, installation_id=installation, inference_key=key)


def test_issued_read_and_write_credentials_are_separated():
    """Only prepared read authority receives inference; publisher remains independent."""
    module = _load()
    assert hasattr(module, "phase_environment_from_issuance"), "missing issuance-scoped consumer"
    for phase in ("prepare", "publish"):
        env = module.phase_environment_from_issuance(
            phase, _token_response(phase), scope=_scope(), reviewer_actor="cwl-noema-review[bot]",
            installation_id=7, inference_key="SYNTHETIC_INFERENCE_ONLY",
        )
        assert env["GH_TOKEN"] == "SYNTHETIC_FIXTURE_ONLY"
        assert ("NOEMA_LLM_API_KEY" in env) is (phase == "prepare")
        module.require_phase_environment(phase, env)


def _envelope_payload():
    """An otherwise-valid synthetic eight-field producer output."""
    scope = _scope()
    return {"schema_version": 1, "repository": scope["repository"],
            "pull_request_number": scope["number"], "expected_head": scope["head"],
            "expected_base": scope["base"], "pull_request_author": scope["author"],
            "reviewer_actor": scope["reviewer"], "verdict": {"decision": "approve"}}


@pytest.mark.parametrize("kind", ["empty", "oversize", "malformed", "missing", "wrong_keys", "version", "identity", "verdict"])
def test_envelope_characterization_rejections(tmp_path, kind):
    """Exercise each bounded local-envelope refusal without inference or publication."""
    payload = _envelope_payload()
    if kind == "version":
        payload["schema_version"] = True
    if kind == "identity":
        payload["reviewer_actor"] = "foreign[bot]"
    if kind == "verdict":
        payload["verdict"] = None
    if kind == "wrong_keys":
        payload = {}
    raw = json.dumps(payload).encode()
    if kind == "empty":
        raw = b""
    if kind == "oversize":
        raw = b" " * (2 * 1024 * 1024 + 1)
    if kind == "malformed":
        raw = b"{"
    path = tmp_path / "envelope"
    if kind != "missing":
        path.write_bytes(raw)
        path.chmod(0o600)
    with pytest.raises(ValueError, match="prepared envelope"):
        _load().require_prepared_envelope(path, _scope())


@pytest.mark.parametrize("kind", ["relative", "symlink", "fifo", "entrypoint", "interpreter"])
def test_loader_characterization_rejections(tmp_path, kind):
    """Invalid namespace and interpreter controls never reach a child process."""
    import os
    import sys

    raw, files, accepted = _fixture()
    root = tmp_path / "source"
    root.mkdir()
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    interpreter = Path(sys.executable)
    if kind == "relative":
        root = Path("relative")
    if kind == "symlink":
        (root / "alias").symlink_to(next(iter(files)))
    if kind == "fifo":
        os.mkfifo(root / "pipe")
    if kind == "entrypoint":
        manifest = json.loads(raw)
        manifest["entrypoint"] = "other.py"
        (root / next(iter(files))).unlink()
        (root / "other.py").write_bytes(b"# inert")
        manifest["files"] = {"other.py": hashlib.sha256(b"# inert").hexdigest()}
        raw = json.dumps(manifest).encode()
        accepted = hashlib.sha256(raw).hexdigest()
    if kind == "interpreter":
        interpreter = Path("relative-python")
    with pytest.raises(ValueError):
        _load().load_noema_tooling(root, raw, accepted_digest=accepted, interpreter=interpreter,
            phase_environment=lambda _: {"NOEMA_LLM_MODEL": "auto"},
            child_runner=lambda *_args, **_kwargs: pytest.fail("must not execute")
        ).prepare_verdict("ContextualWisdomLab/example", 7, "c" * 40, tmp_path / "verdict")


def test_scope_missing_fields_and_unsupported_phase_characterization():
    """Incomplete authority records and unknown phase names fail closed."""
    module = _load()
    with pytest.raises(ValueError, match="review scope"):
        module.require_review_scope({}, {})
    with pytest.raises(ValueError, match="phase environment"):
        module.require_phase_environment("foreign", {})


def test_bound_tooling_runs_real_two_phase_cli_with_inert_fixture_gate(tmp_path):
    """Execute actual CLI producer/publisher bytes, not live inference or GitHub."""
    import sys

    tooling_root = tmp_path / "tooling"
    files = {
        ".github/actions/noema-review/two_phase.py": (ROOT / ".github/actions/noema-review/two_phase.py").read_bytes(),
        "scripts/__init__.py": b"",
        "scripts/ci/__init__.py": b"",
        "scripts/ci/noema_review_gate.py": b'''"""INERT FIXTURE ONLY: not the production gate or provider."""
import json
import os
from pathlib import Path
PRIMARY_REVIEW_AUTHORS = {"opencode-agent[bot]"}
def fetch_pr(repo, number):
    return {"state":"OPEN","isDraft":False,"headRefOid":"c"*40,"baseRefOid":"d"*40,"author":{"login":"seonghobae"}}
def require_expected_head(pr, head):
    assert pr["headRefOid"] == head
def current_actor():
    return "cwl-noema-review[bot]"
def require_distinct_pr_author(pr, actor):
    assert pr["author"]["login"] != actor
    return pr["author"]["login"]
def existing_noema_review(*args):
    return False
def fetch_diff(*args):
    return "FIXTURE DIFF", False
def fetch_changed_files(*args):
    return [("src/a.py", "MODIFIED")]
def build_review_context(*args):
    return "FIXTURE CONTEXT"
def call_llm(*args):
    assert os.environ["FIXTURE_PHASE"] == "prepare"
    return {"decision":"approve", "summary":"FIXTURE ONLY"}
def submit_review(repo, number, pr, actor, verdict):
    assert os.environ["FIXTURE_PHASE"] == "publish"
    Path(os.environ["FIXTURE_SINK"]).write_text(json.dumps({"fixture_only":True,"head":pr["headRefOid"],"actor":actor,"verdict":verdict}))
''',
    }
    for name, data in files.items():
        path = tooling_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    raw, _, _ = _fixture()
    manifest = json.loads(raw)
    manifest["files"] = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    raw = json.dumps(manifest).encode()
    accepted = hashlib.sha256(raw).hexdigest()
    sink = tmp_path / "fixture-sink.json"

    def phase_environment(phase):
        environment = _load().phase_environment_from_issuance(
            phase, _token_response(phase), scope=_scope(),
            reviewer_actor="cwl-noema-review[bot]", installation_id=7,
            inference_key="SYNTHETIC_INFERENCE_ONLY",
        )
        environment.update(FIXTURE_PHASE=phase, FIXTURE_SINK=str(sink))
        return environment

    loader = lambda: _load().load_noema_tooling(
        tooling_root, raw, accepted_digest=accepted, interpreter=Path(sys.executable),
        phase_environment=phase_environment,
    )
    assert _load().run_review(
        raw, accepted_digest=accepted, source_files=files, scope=_scope(),
        fetch_live=lambda: {**_scope(), "state": "OPEN", "draft": False},
        require_execution_admission=lambda: None, load_tooling=loader,
        refresh_publisher=lambda: None, private_parent=tmp_path,
    ) == 0
    assert json.loads(sink.read_text())["fixture_only"] is True
    assert not list(tmp_path.glob("premerge-review-*"))
    assert {name: (tooling_root / name).read_bytes() for name in files} == files
