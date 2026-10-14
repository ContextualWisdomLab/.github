"""Cached Docker observations must never alter original Strix authentication."""

from __future__ import annotations

import asyncio
import importlib.metadata
from pathlib import Path
import runpy
import sys
import types

import pytest

from tests.test_strix_llm_timeout_contract import _fake_sandbox_modules, _load_launcher


IDENTITY = "a" * 64
IMAGE = "sha256:" + "b" * 64
FIXTURE = Path(__file__).parent / "fixtures" / "strix_login_as_guest_1_5_3.py"


class Container:
    """Supply existing Docker attributes and forbid every lifecycle or refresh call."""

    id = IDENTITY

    def __init__(self):
        self.attrs = {"Id": IDENTITY, "Image": IMAGE,
                      "State": {"Status": "running", "ExitCode": 0, "OOMKilled": False}}

    def reload(self):
        pytest.fail("Observer must not refresh Docker state")

    def remove(self):
        pytest.fail("Observer must not remove Docker containers")


class Inner:
    """Mirror the reviewed SDK's bound Docker object and identity fields."""

    def __init__(self, container):
        self._container = container
        self.container_id = IDENTITY


class Session:
    """Simulate only curl I/O for the unchanged pinned guest-token function."""

    def __init__(self, payload=b'{"data":{"loginAsGuest":{"token":{"accessToken":"guest-secret"}}}}', code=0):
        self._inner = Inner(Container())
        self.payload = payload
        self.code = code
        self.calls = []

    async def exec(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        assert args[0:3] == ("curl", "-fsS", "-X")
        assert args[-1] == "http://127.0.0.1:48080/graphql"
        assert kwargs == {"timeout": 15}
        return types.SimpleNamespace(ok=lambda: self.code == 0, stdout=self.payload,
                                     stderr=b"synthetic connection refused", exit_code=self.code)


def original_login():
    """Use the unchanged parser/token checks with only the retry clock replaced."""
    function = runpy.run_path(str(FIXTURE))["_login_as_guest"]
    async def sleep(_delay):
        return None
    function.__globals__["asyncio"] = types.SimpleNamespace(sleep=sleep)
    return function


def test_fixture_preserves_the_exact_pinned_authentication_source():
    import ast
    import hashlib
    source = FIXTURE.read_text()
    node = next(node for node in ast.parse(source).body
                if isinstance(node, ast.AsyncFunctionDef) and node.name == "_login_as_guest")
    assert hashlib.sha256(ast.get_source_segment(source, node).encode()).hexdigest() == (
        "4e23ddba5879b791440169980433f83b17f1046892d4ee6d2496f27a56853d1c"
    )


@pytest.mark.parametrize("state", ["running", "exited", "dead", "removing"])
def test_even_cached_terminal_state_does_not_skip_original_authentication(state, capsys):
    launcher = _load_launcher()
    session = Session()
    session._inner._container.attrs["State"]["Status"] = state
    observed = launcher.wrap_sandbox_authentication(original_login(), Inner)
    assert asyncio.run(observed(session, container_url="http://127.0.0.1:48080")) == "guest-secret"
    assert len(session.calls) == 1
    output = capsys.readouterr().err
    assert "phase=authentication_start freshness=cached" in output
    assert "phase=authentication_success freshness=cached" in output
    assert f"image_config_id={IMAGE} status={state} exit_code=0 oom_killed=false" in output
    assert "guest-secret" not in output and IDENTITY not in output


@pytest.mark.parametrize("payload,code,message", [
    (b'{"data":{"loginAsGuest":{"token":{}}}}', 0, "returned no token"),
    (b"not-json", 0, "unparseable response"),
    (b"", 7, "curl exit 7"),
])
def test_actual_token_parser_and_retry_count_are_unchanged(payload, code, message, capsys):
    launcher = _load_launcher()
    session = Session(payload, code)
    observed = launcher.wrap_sandbox_authentication(original_login(), Inner)
    with pytest.raises(RuntimeError, match=message):
        asyncio.run(observed(session, container_url="http://127.0.0.1:48080", attempts=2))
    assert len(session.calls) == 2
    output = capsys.readouterr().err
    assert "phase=authentication_failure" in output
    assert "not-json" not in output and "connection refused" not in output


@pytest.mark.parametrize("kind", ["error", "cancel"])
def test_exact_original_exception_and_cancellation_survive_observation(kind, capsys):
    launcher = _load_launcher()
    error = RuntimeError("private original error") if kind == "error" else asyncio.CancelledError()
    calls = []
    async def original(session, *, container_url, attempts=10):
        calls.append((session, container_url, attempts))
        raise error
    session = Session()
    observed = launcher.wrap_sandbox_authentication(original, Inner)
    with pytest.raises(type(error)) as result:
        asyncio.run(observed(session, container_url="http://127.0.0.1:48080", attempts=3))
    assert result.value is error
    assert calls == [(session, "http://127.0.0.1:48080", 3)]
    assert "private" not in capsys.readouterr().err


@pytest.mark.parametrize("mutation", ["foreign-inner", "missing-object", "wrong-id", "missing-id", "object-id",
                                      "bad-attrs", "bad-state", "malformed-fields", "cache-error"])
def test_missing_or_malformed_cached_binding_emits_only_omitted_values(mutation, capsys):
    launcher = _load_launcher()
    session = Session()
    container = session._inner._container
    if mutation == "foreign-inner":
        session._inner = object()
    elif mutation == "missing-object":
        del session._inner._container
    elif mutation == "wrong-id":
        container.attrs["Id"] = "c" * 64
    elif mutation == "missing-id":
        del container.attrs["Id"]
    elif mutation == "object-id":
        container.id = "c" * 64
    elif mutation == "bad-attrs":
        container.attrs = []
    elif mutation == "bad-state":
        container.attrs = {"Id": IDENTITY, "Image": "private-tag", "State": "private-state"}
    elif mutation == "malformed-fields":
        container.attrs = {"Id": IDENTITY, "Image": "sha256:" + "B" * 64,
                           "State": {"Status": "private\nstatus", "ExitCode": True, "OOMKilled": "private"}}
    else:
        class BrokenInner(Inner):
            @property
            def container_id(self):
                raise RuntimeError("private observer error")
            @container_id.setter
            def container_id(self, value):
                pass
        session._inner = BrokenInner(container)
    observed = launcher.wrap_sandbox_authentication(original_login(), Inner)
    assert asyncio.run(observed(session, container_url="http://127.0.0.1:48080")) == "guest-secret"
    output = capsys.readouterr().err
    assert "image_config_id=<omitted> status=<omitted> exit_code=<omitted> oom_killed=<omitted>" in output
    assert "private" not in output


def test_non_docker_binding_is_not_inspected(capsys):
    """A foreign inner session keeps guest parsing without private Docker access."""
    launcher = _load_launcher()
    class ForeignInner:
        @property
        def _container(self):
            raise AssertionError("Non-Docker private attributes were accessed")
    session = Session()
    session._inner = ForeignInner()
    observed = launcher.wrap_sandbox_authentication(original_login(), Inner)
    assert asyncio.run(observed(session, container_url="http://127.0.0.1:48080")) == "guest-secret"
    assert "image_config_id=<omitted>" in capsys.readouterr().err


def test_invalid_phase_and_failed_output_do_not_change_authentication(monkeypatch, capsys):
    launcher = _load_launcher()
    session = Session()
    launcher.emit_sandbox_diagnostic(session, "private-phase", Inner)
    assert capsys.readouterr().err == ""
    class ClosedOutput:
        def write(self, value):
            raise OSError("private output failure")
    monkeypatch.setattr(sys, "stderr", ClosedOutput())
    observed = launcher.wrap_sandbox_authentication(original_login(), Inner)
    assert asyncio.run(observed(session, container_url="http://127.0.0.1:48080")) == "guest-secret"


def test_installation_only_wraps_guest_function_and_never_touches_backend_or_settings(monkeypatch, capsys):
    launcher = _load_launcher()
    bootstrap = _fake_sandbox_modules(monkeypatch)
    monkeypatch.setitem(sys.modules, "strix", types.ModuleType("strix"))
    sys.modules["agents.sandbox.sandboxes.docker"].DockerSandboxSession = Inner
    config = types.ModuleType("strix.config")
    config.load_settings = lambda: pytest.fail("Observer must not create/cache settings")
    monkeypatch.setitem(sys.modules, "strix.config", config)
    backends = sys.modules["strix.runtime.backends"]
    factory = backends.get_backend("docker")
    original = bootstrap._login_as_guest
    launcher.install_sandbox_diagnostics()
    assert bootstrap._login_as_guest.__wrapped__ is original
    assert backends.get_backend("docker") is factory
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("failure", ["version", "missing-sdk", "import", "abi"])
def test_unavailable_diagnostics_do_not_block_the_existing_scan(monkeypatch, capsys, failure):
    launcher = _load_launcher()
    bootstrap = _fake_sandbox_modules(monkeypatch)
    monkeypatch.setitem(sys.modules, "strix", types.ModuleType("strix"))
    original = bootstrap._login_as_guest
    if failure == "version":
        monkeypatch.setattr(importlib.metadata, "version", lambda name: "0.19.5")
    elif failure == "missing-sdk":
        def missing(name):
            raise importlib.metadata.PackageNotFoundError(name)
        monkeypatch.setattr(importlib.metadata, "version", missing)
    elif failure == "import":
        monkeypatch.setitem(sys.modules, "agents.sandbox.sandboxes.docker", None)
    else:
        bootstrap._login_as_guest = lambda: None
        original = bootstrap._login_as_guest
    launcher.install_sandbox_diagnostics()
    assert bootstrap._login_as_guest is original
    assert capsys.readouterr().err == "STRIX_SANDBOX_DIAGNOSTICS unavailable\n"


def test_unavailable_marker_output_error_is_nonfatal(monkeypatch):
    launcher = _load_launcher()
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "unsupported")
    class ClosedOutput:
        def write(self, value):
            raise OSError("private output failure")
    monkeypatch.setattr(sys, "stderr", ClosedOutput())
    launcher.install_sandbox_diagnostics()
