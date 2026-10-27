"""Actual finite-child F1/F2/F3 regressions; never native custody evidence."""
import ast
import inspect
import json
import signal
import sys
import textwrap

import pytest
from scripts.ci import fast_mlsirm_local_supervisor as m
from tests.test_fast_mlsirm_local_supervisor import lock_probe, receipt_input


def source_line(method, predicate):
    """Find one semantic statement in the exact executed function, not stale lines."""
    lines, start = inspect.getsourcelines(method)
    tree = ast.parse(textwrap.dedent("".join(lines)))
    selected = [node for node in ast.walk(tree) if predicate(node)]
    assert len(selected) == 1
    return start + selected[0].lineno - 1


@pytest.mark.parametrize("corrupt", [False, True], ids=["valid-bytes", "wrong-run"])
def test_f1_sigint_before_consumption_never_reconciles_unvalidated_success(tmp_path, corrupt):
    """Interrupt the real consumer call after actual wait; preserve same owner."""
    owner = m.Supervisor(tmp_path)
    path, digest, binding = receipt_input(tmp_path, owner)
    line = source_line(owner.run, lambda node: isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "receipts" and node.func.attr == "validate")
    code_object = owner.run.__func__.__code__
    fired = False

    def tracer(frame, event, arg):
        nonlocal fired
        if frame.f_code is code_object and event == "line" and frame.f_lineno == line and not fired:
            fired = True
            if corrupt:
                report = tmp_path / "local-receipt.json"
                original = report.read_bytes()
                (tmp_path / "original-emitted-receipt.json").write_bytes(original)
                data = json.loads(original)
                data["calls"][0]["run_id"] = "999"
                report.write_text(json.dumps(data))
            signal.raise_signal(signal.SIGINT)
        return tracer

    previous = sys.gettrace()
    sys.settrace(tracer)
    try:
        with pytest.raises(KeyboardInterrupt):
            owner.run("receipt", input_path=path, input_sha256=digest, expected=binding)
    finally:
        sys.settrace(previous)
    assert fired and owner.waited and owner.child.returncode == 0
    assert lock_probe(tmp_path) == 9
    assert not (tmp_path / "settlement.json").exists()
    if corrupt:
        with pytest.raises(ValueError, match="call binding mismatch"):
            m.receipts.validate((tmp_path / "local-receipt.json").read_bytes(), (tmp_path / "local-junit.xml").read_bytes(), binding)
    child = owner.child
    result = owner.reconcile()
    assert owner.child is child
    assert result["status"] != "local_success"
    assert result.get("receipt_validated") is False
    assert result["wait_returncode"] == 0
    assert json.loads((tmp_path / "settlement.json").read_text()) == result
    assert lock_probe(tmp_path) == 0


@pytest.mark.parametrize("validation", ["absent", False, 1], ids=["absent", "false", "integer-one"])
def test_f1_finish_rejects_receipt_success_without_completed_validation(tmp_path, monkeypatch, validation):
    """Controlled owner-state fault cannot bypass the final receipt gate."""
    owner = m.Supervisor(tmp_path)
    path, digest, binding = receipt_input(tmp_path, owner)
    interruption = KeyboardInterrupt("fixture consumer interruption")

    def interrupt(*args):
        raise interruption

    monkeypatch.setattr(m.receipts, "validate", interrupt)
    with pytest.raises(KeyboardInterrupt) as caught:
        owner.run("receipt", input_path=path, input_sha256=digest, expected=binding)
    assert caught.value is interruption
    owner.result["status"] = "local_success"
    if validation == "absent":
        owner.result.pop("receipt_validated", None)
    else:
        owner.result["receipt_validated"] = validation
    try:
        with pytest.raises(ValueError, match="receipt validation incomplete"):
            owner.reconcile()
        assert lock_probe(tmp_path) == 9
        assert not (tmp_path / "settlement.json").exists()
    finally:
        if owner.lock_fd is not None:
            owner.result["status"] = "receipt_interrupted"
            owner.result["receipt_validated"] = False
            owner.reconcile()


@pytest.mark.parametrize("mode,expected_code", [("success", 0), ("failure", 17)])
def test_f2_sigint_after_exact_wait_preserves_integer(tmp_path, mode, expected_code):
    """Actual SIGINT on the semantic wait return must not discard child status."""
    owner = m.Supervisor(tmp_path)
    line = source_line(owner._wait, lambda node: isinstance(node, ast.Return))
    code_object = owner._wait.__func__.__code__
    fired = False

    def tracer(frame, event, arg):
        nonlocal fired
        if frame.f_code is code_object and event == "line" and frame.f_lineno == line and not fired:
            fired = True
            signal.raise_signal(signal.SIGINT)
        return tracer

    previous = sys.gettrace()
    sys.settrace(tracer)
    try:
        with pytest.raises(KeyboardInterrupt):
            owner.run(mode)
    finally:
        sys.settrace(previous)
    assert fired and owner.waited and owner.child.returncode == expected_code
    saved = json.loads((tmp_path / "settlement.json").read_text())
    assert type(saved["wait_returncode"]) is int
    assert saved["wait_returncode"] == expected_code
    assert saved["status"] == "interrupted"
    assert lock_probe(tmp_path) == 0


@pytest.mark.parametrize("field,value", [("owner", None), ("owner", False), ("owner", 17), ("result", None), ("result", False), ("result", 17)], ids=["owner-none", "owner-bool", "owner-mismatch", "result-none", "result-bool", "result-mismatch"])
def test_f2_finish_requires_exact_owner_and_result_wait_code(tmp_path, monkeypatch, field, value):
    """A Boolean waited bit alone cannot retire an uncertain settlement."""
    owner = m.Supervisor(tmp_path)
    write = m._atomic_write

    def refuse(*args):
        raise OSError("fixture journal refusal")

    monkeypatch.setattr(m, "_atomic_write", refuse)
    with pytest.raises(OSError, match="fixture journal refusal"):
        owner.run("success")
    monkeypatch.setattr(m, "_atomic_write", write)
    if field == "owner":
        owner.wait_returncode = value
    else:
        owner.result["wait_returncode"] = value
    try:
        with pytest.raises(ValueError, match="original child settlement unknown"):
            owner._finish()
        assert owner in m._UNRESOLVED
        assert lock_probe(tmp_path) == 9
        assert not (tmp_path / "settlement.json").exists()
    finally:
        if owner.lock_fd is not None:
            owner.wait_returncode = 0
            owner.result["wait_returncode"] = 0
            owner.reconcile()


def test_f2_interrupted_reconcile_recovers_captured_wait_code(tmp_path, monkeypatch):
    """A second interrupt during same-owner wait recovery must not lose its exit."""
    owner = m.Supervisor(tmp_path)
    original = owner._wait

    def refuse(timeout):
        raise OSError("fixture initial wait refusal")

    monkeypatch.setattr(owner, "_wait", refuse)
    with pytest.raises(OSError, match="fixture initial wait refusal"):
        owner.run("stall")
    assert lock_probe(tmp_path) == 9
    interruption = KeyboardInterrupt("fixture recovery postwait interruption")

    def interrupt_after_wait(timeout):
        original(timeout)
        raise interruption

    monkeypatch.setattr(owner, "_wait", interrupt_after_wait)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            owner.reconcile()
        assert caught.value is interruption
        assert owner.waited and type(owner.child.returncode) is int
        assert lock_probe(tmp_path) == 9
        monkeypatch.setattr(owner, "_wait", original)
        result = owner.reconcile()
        assert result["wait_returncode"] == owner.child.returncode
        assert result["status"] == "interrupted"
        assert lock_probe(tmp_path) == 0
    finally:
        if owner.lock_fd is not None:
            owner.result["wait_returncode"] = owner.child.returncode
            monkeypatch.setattr(owner, "_wait", original)
            owner.reconcile()


@pytest.mark.parametrize("mode", ["success", "failure", "receipt"])
def test_f3_active_sigchld_ignore_rejects_before_acquisition(tmp_path, mode):
    """Refuse incompatible active library policy without changing that policy."""
    owner = m.Supervisor(tmp_path)
    kwargs = {}
    if mode == "receipt":
        path, digest, binding = receipt_input(tmp_path, owner)
        kwargs = dict(input_path=path, input_sha256=digest, expected=binding)
    before = set(tmp_path.iterdir())
    previous = signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    try:
        with pytest.raises(ValueError, match="exclusive child reaping requires default SIGCHLD"):
            owner.run(mode, **kwargs)
        assert signal.getsignal(signal.SIGCHLD) == signal.SIG_IGN
        assert owner.child is None and owner.lock_fd is None and not owner.claimed
        assert set(tmp_path.iterdir()) == before
    finally:
        signal.signal(signal.SIGCHLD, previous)


def test_f3_custom_reaper_policy_is_not_admitted(tmp_path):
    """Do not guess whether a custom process-global handler will reap our child."""
    owner = m.Supervisor(tmp_path)

    def handler(signum, frame):
        pass

    previous = signal.signal(signal.SIGCHLD, handler)
    try:
        with pytest.raises(ValueError, match="exclusive child reaping requires default SIGCHLD"):
            owner.run("failure")
        assert signal.getsignal(signal.SIGCHLD) is handler
        assert owner.child is None and list(tmp_path.iterdir()) == []
    finally:
        signal.signal(signal.SIGCHLD, previous)


def test_f3_main_active_ignore_rejects_without_attempt(tmp_path, capsys):
    """The exported main must refuse in an already-running embedding process."""
    previous = signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    try:
        code = m.main(["local", "--root", str(tmp_path), "--mode", "failure"])
        unchanged = signal.getsignal(signal.SIGCHLD) == signal.SIG_IGN
    finally:
        signal.signal(signal.SIGCHLD, previous)
    assert code == 1
    assert unchanged and list(tmp_path.iterdir()) == []
    assert "LOCAL_ATTEMPT_REJECTED" in capsys.readouterr().err
